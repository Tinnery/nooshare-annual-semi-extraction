"""E1 判定程序：章节完备性判定。

E1 外部客观标准 = 章节完备性 = §2 号准则当年版本
判定函数：reg_version(period, disclosure_date) → 法定章节集；
         算 missing/extra/order；三态分别计数
通过条件：NOT_DISCLOSED 打监管违规 flag；EXTRACTION_FAILURE 判工程 fail；
         NOT_APPLICABLE 不计缺失
失败归类：版本选错 / 准则串用 / 三态混计 / 标题误升格

本模块实现 E1 判定程序的代码框架。
前提条件：reg_version 适用规则已于 2026-11-13 由 Human Gate 裁决为 by_period_end。
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .spec_loader import SpecLoader


class MissingState(Enum):
    """缺失三态。"""
    NOT_APPLICABLE = "NOT_APPLICABLE"      # 法规不要求（如半年报无某些章节）
    NOT_DISCLOSED = "NOT_DISCLOSED"        # 法规要求但未披露 → 监管 flag
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"  # 工程失败 → 判 fail


@dataclass
class ChapterCompliance:
    """单份报告的章节合规结果。"""
    report_id: str
    standard: str           # "第2号" | "第3号"
    version: str            # 如 "〔2025〕3号"
    effective_from: str     # 如 "2025-07-01"
    
    # 法定必披章节
    required_chapters: list[str]
    
    # 实际披露章节
    disclosed_chapters: list[str]
    
    # 三态分类
    missing: list[str]              # NOT_DISCLOSED: 法定要求但未披露
    not_applicable: list[str]       # NOT_APPLICABLE: 法规不要求
    extraction_failures: list[str]  # EXTRACTION_FAILURE: 工程失败
    
    # 顺序与多余
    order_violations: list[tuple[str, str]]  # (expected_before, expected_after)
    extra_chapters: list[str]       # 非法定章节（可能是子章节误升格）
    
    @property
    def is_compliant(self) -> bool:
        """是否合规（无 NOT_DISCLOSED 且无 EXTRACTION_FAILURE）。"""
        return len(self.missing) == 0 and len(self.extraction_failures) == 0
    
    @property
    def compliance_rate(self) -> float:
        """合规率（NOT_APPLICABLE 不计入分母）。"""
        applicable = [c for c in self.required_chapters if c not in self.not_applicable]
        if not applicable:
            return 1.0
        disclosed = [c for c in applicable if self._is_disclosed(c)]
        return len(disclosed) / len(applicable)
    
    def _is_disclosed(self, required: str) -> bool:
        """检查法定章节是否已披露（支持模糊匹配 + 拆分匹配）。"""
        # 先尝试单章节匹配
        for disclosed in self.disclosed_chapters:
            if self._matches(required, disclosed):
                return True
        # 再尝试拆分匹配（法定章节被拆分成多个实际章节）
        if self._matches_split(required, self.disclosed_chapters):
            return True
        return False
    
    @staticmethod
    def _matches(required: str, disclosed: str) -> bool:
        """检查披露章节是否匹配法定章节（模糊匹配）。
        
        匹配规则：
        1. 完全相等
        2. 章节标记可以互换（"第X章" 和 "第X节" 在某些情况下等价）
        3. 披露章节包含法定章节的关键词（如 "第一节 公司简介" 匹配 "第一节 公司简介和主要财务指标"）
        4. 法定章节名称是披露章节的子串（如 "重要提示" 在 "重要提示、目录和释义" 中）
        5. 标题措辞差异（如 "与" vs "和"）
        6. 拆分匹配：法定章节被拆分成多个实际章节（如 "公司简介和主要财务指标" 被拆成 "公司简介" + "会计数据和财务指标"）
        """
        # 完全相等
        if required == disclosed:
            return True
        
        # 提取 marker 和 name
        req_parts = required.split(" ", 1)
        disc_parts = disclosed.split(" ", 1)
        
        if len(req_parts) == 2 and len(disc_parts) == 2:
            req_marker, req_name = req_parts
            disc_marker, disc_name = disc_parts
            
            # 检查 marker 是否匹配（允许"章"和"节"互换）
            marker_matches = (
                req_marker == disc_marker or
                (req_marker.replace("章", "节") == disc_marker.replace("章", "节"))
            )
            
            if marker_matches:
                # 标准化标题（替换"与"为"和"，去除多余空格）
                req_name_norm = req_name.replace("与", "和").replace("  ", " ").strip()
                disc_name_norm = disc_name.replace("与", "和").replace("  ", " ").strip()
                
                # name 互相包含即可
                if req_name_norm in disc_name_norm or disc_name_norm in req_name_norm:
                    return True
                
                # 提取关键词进行匹配
                req_keywords = set(req_name_norm)
                disc_keywords = set(disc_name_norm)
                # 如果关键词重叠度超过 70%，认为匹配
                if len(req_keywords) > 0 and len(disc_keywords) > 0:
                    overlap = len(req_keywords & disc_keywords)
                    similarity = overlap / max(len(req_keywords), len(disc_keywords))
                    if similarity > 0.7:
                        return True
        
        # 子串匹配（兜底）
        if required in disclosed or disclosed in required:
            return True
        
        return False
    
    @staticmethod
    def _matches_split(required: str, disclosed_list: list[str]) -> bool:
        """检查法定章节是否被拆分成多个实际章节。
        
        例如：法定章节 "第二节 公司简介和主要财务指标" 可能被拆分成：
        - "第一章  公司简介"
        - "第二章  会计数据和财务指标"
        
        匹配逻辑：
        1. 提取法定章节的关键词（如 "公司简介", "财务指标"）
        2. 检查这些关键词是否分散在多个实际章节中（不要求 marker 匹配，因为拆分后编号可能不同）
        3. 如果关键词覆盖率超过阈值，认为匹配
        """
        # 提取 marker 和 name
        req_parts = required.split(" ", 1)
        if len(req_parts) != 2:
            return False
        
        req_marker, req_name = req_parts
        req_name_norm = req_name.replace("与", "和").replace("  ", " ").strip()
        
        # 提取关键词（按"和"、"及"、"、"分割）
        keywords = []
        for sep in ["和", "及", "、"]:
            if sep in req_name_norm:
                keywords = [k.strip() for k in req_name_norm.split(sep)]
                break
        
        if not keywords:
            # 没有分隔符，无法判断拆分
            return False
        
        # 过滤空关键词
        keywords = [k for k in keywords if k]
        if not keywords:
            return False
        
        # 检查每个关键词是否在实际章节中出现（不要求 marker 匹配）
        matched_keywords = set()
        for keyword in keywords:
            for disclosed in disclosed_list:
                disc_parts = disclosed.split(" ", 1)
                if len(disc_parts) == 2:
                    disc_marker, disc_name = disc_parts
                    disc_name_norm = disc_name.replace("与", "和").replace("  ", " ").strip()
                    
                    # 关键词匹配（不检查 marker，因为拆分后编号可能不同）
                    if keyword in disc_name_norm:
                        matched_keywords.add(keyword)
                        break
        
        # 如果关键词覆盖率超过 50%，认为匹配
        return len(matched_keywords) >= len(keywords) * 0.5


class E1Judge:
    """E1 判定程序。
    
    使用方式：
        judge = E1Judge(spec_loader)
        result = judge.judge(report_id, period, disclosure_date, disclosed_chapters)
        
    前提条件：
        - 法规原文已采集并登记 sha256（已完成）
        - 章节结构已提取（已完成）
        - 法定必披章节清单已构建（已完成）
        - reg_version 适用规则已裁决（by_period_end，2026-11-13 Human Gate）
    """
    
    def __init__(self, spec_loader: SpecLoader):
        self.spec_loader = spec_loader
        self.legal_chapters = spec_loader.load_legal_chapters()
        self.regulatory_versions = spec_loader.load_regulatory_versions()
        
        # 检查前提条件
        if self.regulatory_versions["acquisition_status"] != "COMPLETED":
            raise RuntimeError("法规原文未采集，E1 不得运行")
        
        if self.regulatory_versions["applicability_rule_status"] == "UNRESOLVED":
            # 适用规则未裁决，允许初始化但不允许运行 judge()
            self._applicability_resolved = False
        else:
            self._applicability_resolved = True
    
    def resolve_version(self, period: int, report_year: int, disclosure_date: str = None) -> dict:
        """根据期间和报告年份确定适用法规版本。
        
        前提：applicability_rule 已裁决。
        
        Args:
            period: 报告期间（2=半年报，4=年报）
            report_year: 报告年份（如 2024 表示 2024 年年报或 2024 年半年报）
            disclosure_date: 披露日期（YYYY-MM-DD），仅 by_disclosure_date 模式需要
        
        Returns:
            适用的法规版本字典
        """
        if not self._applicability_resolved:
            raise RuntimeError(
                "reg_version 适用规则未裁决（披露日 vs 报告期末），E1 判定程序不得运行。"
                "请 Human Gate 裁决后更新 regulatory_versions.json 的 applicability_rule_status。"
            )
        
        # 确定准则编号
        if period == 4:
            standard = "第2号"  # 年报
        elif period == 2:
            standard = "第3号"  # 半年报
        else:
            raise ValueError(f"period 必须是 2 或 4，实际: {period}")
        
        # 根据适用规则选择版本
        rule = self.regulatory_versions["applicability_rule"]
        versions = [
            v for v in self.regulatory_versions["versions"]
            if v["standard"] == standard
        ]
        
        # 按施行日排序
        versions.sort(key=lambda v: v["effective_from"])
        
        if rule == "by_disclosure_date":
            if disclosure_date is None:
                raise ValueError("by_disclosure_date 模式必须提供 disclosure_date")
            effective_date = disclosure_date
        elif rule == "by_period_end":
            # 报告期末：period=4 → "YYYY-12-31"；period=2 → "YYYY-06-30"
            if period == 4:
                effective_date = f"{report_year}-12-31"
            else:
                effective_date = f"{report_year}-06-30"
        else:
            raise ValueError(f"未知的适用规则: {rule}")
        
        # 找到 effective_date 时有效的版本
        applicable = None
        for v in versions:
            if v["effective_from"] <= effective_date:
                applicable = v
            else:
                break
        
        if applicable is None:
            raise ValueError(
                f"无法确定适用版本：period={period}, report_year={report_year}, "
                f"disclosure_date={disclosure_date}, effective_date={effective_date}"
            )
        
        return applicable
    
    def judge(
        self,
        report_id: str,
        period: int,
        report_year: int,
        disclosed_chapters: list[str],
        disclosure_date: str = None,
    ) -> ChapterCompliance:
        """判定单份报告的章节完备性。
        
        Args:
            report_id: 报告唯一标识（如 "000001_2023_4"）
            period: 报告期间（2=半年报，4=年报）
            report_year: 报告年份（如 2023 表示 2023 年年报或 2023 年半年报）
            disclosed_chapters: 实际披露的一级章节标题列表（按顺序）
            disclosure_date: 披露日期（YYYY-MM-DD），仅 by_disclosure_date 模式需要
        
        Returns:
            ChapterCompliance 对象，包含三态分类与合规判定
        """
        # 复用上游 slot_key 契约校验 report_id，防止串报告（铁律 4）。
        # 上游不在 sys.path 时（如独立打包运行）跳过格式校验，不引入强依赖。
        try:
            from annual_semi.completeness import parse_slot_key
            code, parsed_year, parsed_period = parse_slot_key(report_id)
            if parsed_year != report_year or parsed_period != period:
                raise ValueError(
                    f"report_id 与 period/report_year 不一致: {report_id} "
                    f"(period={period}, report_year={report_year})"
                )
        except ImportError:
            pass

        # 解析适用版本
        version = self.resolve_version(period, report_year, disclosure_date)
        standard = version["standard"]
        document_no = version["document_no"]
        effective_from = version["effective_from"]
        
        # 获取法定必披章节
        # 使用 original_file 字段构建 key（如 "no2_2016_31"）
        # original_file 格式为 "regulatory_texts/no2_2016_31.pdf"
        original_file = version["original_file"]
        legal_key = Path(original_file).stem  # 去掉路径和后缀
        legal_info = self.legal_chapters["chapters"].get(legal_key)
        if legal_info is None:
            raise ValueError(f"未找到法定章节清单：{legal_key}")
        
        sections = legal_info["sections"]
        
        # 分类：always required vs conditional
        required_sections = [s for s in sections if s["required"] == "always"]
        conditional_sections = [s for s in sections if s["required"] == "conditional"]
        
        # 三态分类
        missing = []
        not_applicable = []
        extraction_failures = []
        
        # 使用模糊匹配函数（支持单章节匹配 + 拆分匹配）
        def is_disclosed(required_title: str) -> bool:
            """检查法定章节是否已披露（支持模糊匹配和拆分匹配）。"""
            # 先尝试单章节匹配
            for disclosed in disclosed_chapters:
                if ChapterCompliance._matches(required_title, disclosed):
                    return True
            # 再尝试拆分匹配（法定章节被拆分成多个实际章节）
            if ChapterCompliance._matches_split(required_title, disclosed_chapters):
                return True
            return False
        
        for section in required_sections:
            # 构建章节标题（如 "第一节 重要提示"）
            chapter_title = f"{section['marker']} {section['name']}"
            
            if is_disclosed(chapter_title):
                # 已披露
                pass
            else:
                # 检查是否为抽取失败（如章节标题格式异常导致未识别）
                # TODO: 实现抽取失败判定（如检查原文是否存在疑似章节标记）
                # 当前简化处理：视为 NOT_DISCLOSED
                missing.append(chapter_title)
        
        for section in conditional_sections:
            # 条件必披章节：根据条件判断是否适用
            # TODO: 实现条件判定逻辑（如"是否含优先股"）
            # 当前简化处理：视为 NOT_APPLICABLE
            chapter_title = f"{section['marker']} {section['name']}"
            not_applicable.append(chapter_title)
        
        # 顺序检查（使用模糊匹配）
        order_violations = []
        required_order = [f"{s['marker']} {s['name']}" for s in required_sections]
        
        # 构建披露章节与法定章节的映射
        disclosed_to_required = {}
        for disc in disclosed_chapters:
            for req in required_order:
                if ChapterCompliance._matches(req, disc):
                    disclosed_to_required[disc] = req
                    break
        
        # 按披露顺序检查法定章节顺序
        disclosed_required_in_order = [
            disclosed_to_required[disc] 
            for disc in disclosed_chapters 
            if disc in disclosed_to_required
        ]
        
        for i in range(len(disclosed_required_in_order) - 1):
            curr = disclosed_required_in_order[i]
            next_ = disclosed_required_in_order[i + 1]
            if curr in required_order and next_ in required_order:
                curr_idx = required_order.index(curr)
                next_idx = required_order.index(next_)
                if curr_idx > next_idx:
                    order_violations.append((curr, next_))
        
        # 多余章节检查（使用模糊匹配）
        all_legal_titles = [f"{s['marker']} {s['name']}" for s in sections]
        extra_chapters = []
        for disc in disclosed_chapters:
            is_extra = True
            for legal in all_legal_titles:
                if ChapterCompliance._matches(legal, disc):
                    is_extra = False
                    break
            if is_extra:
                extra_chapters.append(disc)
        
        return ChapterCompliance(
            report_id=report_id,
            standard=standard,
            version=document_no,
            effective_from=effective_from,
            required_chapters=required_order,
            disclosed_chapters=disclosed_chapters,
            missing=missing,
            not_applicable=not_applicable,
            extraction_failures=extraction_failures,
            order_violations=order_violations,
            extra_chapters=extra_chapters,
        )


def main():
    """示例用法（适用规则已裁决为 by_period_end）。"""
    import sys
    
    spec_dir = Path(__file__).parent / "spec"
    loader = SpecLoader(spec_dir)
    
    try:
        judge = E1Judge(loader)
    except RuntimeError as e:
        print(f"初始化失败: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 示例：判定一份年报
    # report_id 必须符合上游 slot_key 契约（code_year_period）；
    # 适用规则已裁决为 by_period_end，按报告期末选版本。
    try:
        result = judge.judge(
            report_id="000001_2023_4",
            period=4,  # 年报
            report_year=2023,
            disclosed_chapters=[
                "第一节 重要提示、目录和释义",
                "第二节 公司简介和主要财务指标",
                "第三节 管理层讨论与分析",
                "第四节 公司治理",
                "第五节 环境和社会责任",
                "第六节 重要事项",
                "第七节 股份变动及股东情况",
                "第八节 优先股相关情况",
                "第九节 债券相关情况",
                "第十节 财务报告",
            ],
        )
        print(f"合规: {result.is_compliant}")
        print(f"合规率: {result.compliance_rate:.2%}")
        print(f"缺失 (NOT_DISCLOSED): {result.missing}")
        print(f"不适用 (NOT_APPLICABLE): {result.not_applicable}")
        print(f"抽取失败 (EXTRACTION_FAILURE): {result.extraction_failures}")
        print(f"顺序违规: {result.order_violations}")
        print(f"多余章节: {result.extra_chapters}")
    except RuntimeError as e:
        print(f"判定失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
