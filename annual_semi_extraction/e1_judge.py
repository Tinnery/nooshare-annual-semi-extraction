"""E1 判定程序：章节完备性判定。

E1 外部客观标准 = 章节完备性 = §2 号准则当年版本
判定函数：reg_version(period, disclosure_date) → 法定章节集；
         算 missing/extra/order；三态分别计数
通过条件：NOT_DISCLOSED 打监管违规 flag；EXTRACTION_FAILURE 判工程 fail；
         NOT_APPLICABLE 不计缺失
失败归类：版本选错 / 准则串用 / 三态混计 / 标题误升格

本模块实现 E1 判定程序的代码框架。
前提条件：reg_version 适用规则须由 Human Gate 裁决（披露日 vs 报告期末）。
"""

import json
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
        disclosed = [c for c in applicable if c in self.disclosed_chapters]
        return len(disclosed) / len(applicable)


class E1Judge:
    """E1 判定程序。
    
    使用方式：
        judge = E1Judge(spec_loader)
        result = judge.judge(report_id, period, disclosure_date, disclosed_chapters)
        
    前提条件：
        - 法规原文已采集并登记 sha256（已完成）
        - 章节结构已提取（已完成）
        - 法定必披章节清单已构建（已完成）
        - reg_version 适用规则已裁决（待 Human Gate）
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
    
    def resolve_version(self, period: int, disclosure_date: str) -> dict:
        """根据期间和披露日确定适用法规版本。
        
        前提：applicability_rule 已裁决。
        当前 applicability_rule_status = "UNRESOLVED"，此方法不得调用。
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
        
        # 按施行日排序，找到披露日时有效的版本
        versions.sort(key=lambda v: v["effective_from"])
        
        if rule == "by_disclosure_date":
            effective_date = disclosure_date
        elif rule == "by_period_end":
            # 报告期末：period=4 → "YYYY-12-31"；period=2 → "YYYY-06-30"
            year = int(disclosure_date[:4])
            if period == 4:
                effective_date = f"{year}-12-31"
            else:
                effective_date = f"{year}-06-30"
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
                f"无法确定适用版本：period={period}, disclosure_date={disclosure_date}, "
                f"effective_date={effective_date}"
            )
        
        return applicable
    
    def judge(
        self,
        report_id: str,
        period: int,
        disclosure_date: str,
        disclosed_chapters: list[str],
    ) -> ChapterCompliance:
        """判定单份报告的章节完备性。
        
        Args:
            report_id: 报告唯一标识（如 "000001_2023_4"）
            period: 报告期间（2=半年报，4=年报）
            disclosure_date: 披露日期（YYYY-MM-DD）
            disclosed_chapters: 实际披露的一级章节标题列表（按顺序）
        
        Returns:
            ChapterCompliance 对象，包含三态分类与合规判定
        """
        # 解析适用版本
        version = self.resolve_version(period, disclosure_date)
        standard = version["standard"]
        version_str = version["version"]
        effective_from = version["effective_from"]
        
        # 获取法定必披章节
        legal_key = f"{standard}_{version_str}"
        legal_info = self.legal_chapters["chapters"].get(legal_key)
        if legal_info is None:
            raise ValueError(f"未找到法定章节清单：{legal_key}")
        
        sections = legal_info["sections"]
        required_sections = [s for s in sections if s["required"] == "always"]
        conditional_sections = [s for s in sections if s["required"] == "conditional"]
        
        # 三态分类
        missing = []
        not_applicable = []
        extraction_failures = []
        
        disclosed_set = set(disclosed_chapters)
        
        for section in required_sections:
            section_title = f"{section['marker']} {section['name']}"
            if section_title in disclosed_set:
                # 已披露
                pass
            else:
                # 检查是否为抽取失败（如章节标题格式异常导致未识别）
                # TODO: 实现抽取失败判定（如检查原文是否存在疑似章节标记）
                # 当前简化处理：视为 NOT_DISCLOSED
                missing.append(section_title)
        
        for section in conditional_sections:
            section_title = f"{section['marker']} {section['name']}"
            # 条件必披章节：根据条件判断是否适用
            # TODO: 实现条件判定逻辑（如"是否含优先股"）
            # 当前简化处理：视为 NOT_APPLICABLE
            not_applicable.append(section_title)
        
        # 顺序检查
        order_violations = []
        required_order = [f"{s['marker']} {s['name']}" for s in required_sections]
        disclosed_required = [c for c in disclosed_chapters if c in required_order]
        
        for i in range(len(disclosed_required) - 1):
            curr = disclosed_required[i]
            next_ = disclosed_required[i + 1]
            curr_idx = required_order.index(curr)
            next_idx = required_order.index(next_)
            if curr_idx > next_idx:
                order_violations.append((curr, next_))
        
        # 多余章节检查
        all_legal_titles = [f"{s['marker']} {s['name']}" for s in sections]
        extra_chapters = [
            c for c in disclosed_chapters
            if c not in all_legal_titles
        ]
        
        return ChapterCompliance(
            report_id=report_id,
            standard=standard,
            version=version_str,
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
    """示例用法（需先裁决适用规则）。"""
    import sys
    
    spec_dir = Path(__file__).parent / "spec"
    loader = SpecLoader(spec_dir)
    
    try:
        judge = E1Judge(loader)
    except RuntimeError as e:
        print(f"初始化失败: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 示例：判定一份年报
    # 注意：当前 applicability_rule_status = "UNRESOLVED"，调用 judge() 会失败
    try:
        result = judge.judge(
            report_id="000001_2023_4",
            period=4,  # 年报
            disclosure_date="2024-03-15",
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
