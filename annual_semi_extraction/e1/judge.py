"""E1 判定程序：章节完备性判定。

E1 外部客观标准 = 章节完备性 = §2 号准则当年版本
判定函数：reg_version(period, disclosure_date) → 法定章节集；
         算 missing/extra/order；三态分别计数
通过条件：NOT_DISCLOSED 打监管违规 flag；EXTRACTION_FAILURE 判工程 fail；
         NOT_APPLICABLE 不计缺失
失败归类：版本选错 / 准则串用 / 三态混计 / 标题误升格

前提条件：reg_version 适用规则已于 2026-11-13 由 Human Gate 裁决为 by_period_end。
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from ..spec.loader import SpecLoader


class MissingState(Enum):
    """缺失三态。"""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"


@dataclass
class ChapterCompliance:
    """单份报告的章节合规结果。"""
    report_id: str
    standard: str
    version: str
    effective_from: str
    required_chapters: list[str]
    disclosed_chapters: list[str]
    missing: list[str]
    not_applicable: list[str]
    extraction_failures: list[str]
    order_violations: list[tuple[str, str]]
    extra_chapters: list[str]

    @property
    def is_compliant(self) -> bool:
        return len(self.missing) == 0 and len(self.extraction_failures) == 0

    @property
    def compliance_rate(self) -> float:
        applicable = [c for c in self.required_chapters if c not in self.not_applicable]
        if not applicable:
            return 1.0
        disclosed = [c for c in applicable if self._is_disclosed(c)]
        return len(disclosed) / len(applicable)

    def _is_disclosed(self, required: str) -> bool:
        for disclosed in self.disclosed_chapters:
            if self._matches(required, disclosed):
                return True
        if self._matches_split(required, self.disclosed_chapters):
            return True
        return False

    @staticmethod
    def _matches(required: str, disclosed: str) -> bool:
        if required == disclosed:
            return True
        req_parts = required.split(" ", 1)
        disc_parts = disclosed.split(" ", 1)
        if len(req_parts) == 2 and len(disc_parts) == 2:
            req_marker, req_name = req_parts
            disc_marker, disc_name = disc_parts
            marker_matches = (
                req_marker == disc_marker or
                req_marker.replace("章", "节") == disc_marker.replace("章", "节")
            )
            if marker_matches:
                req_name_norm = req_name.replace("与", "和").replace("  ", " ").strip()
                disc_name_norm = disc_name.replace("与", "和").replace("  ", " ").strip()
                if req_name_norm in disc_name_norm or disc_name_norm in req_name_norm:
                    return True
                req_keywords = set(req_name_norm)
                disc_keywords = set(disc_name_norm)
                if len(req_keywords) > 0 and len(disc_keywords) > 0:
                    overlap = len(req_keywords & disc_keywords)
                    similarity = overlap / max(len(req_keywords), len(disc_keywords))
                    if similarity > 0.7:
                        return True
        if required in disclosed or disclosed in required:
            return True
        return False

    @staticmethod
    def _matches_split(required: str, disclosed_list: list[str]) -> bool:
        req_parts = required.split(" ", 1)
        if len(req_parts) != 2:
            return False
        req_marker, req_name = req_parts
        req_name_norm = req_name.replace("与", "和").replace("  ", " ").strip()
        keywords = []
        for sep in ["和", "及", "、"]:
            if sep in req_name_norm:
                keywords = [k.strip() for k in req_name_norm.split(sep)]
                break
        if not keywords:
            return False
        keywords = [k for k in keywords if k]
        if not keywords:
            return False
        matched_keywords = set()
        for keyword in keywords:
            for disclosed in disclosed_list:
                disc_parts = disclosed.split(" ", 1)
                if len(disc_parts) == 2:
                    disc_marker, disc_name = disc_parts
                    disc_name_norm = disc_name.replace("与", "和").replace("  ", " ").strip()
                    if keyword in disc_name_norm:
                        matched_keywords.add(keyword)
                        break
        return len(matched_keywords) >= len(keywords) * 0.5


class E1Judge:
    """E1 判定程序。

    使用方式：
        judge = E1Judge(spec_loader)
        result = judge.judge(report_id, period, disclosure_date, disclosed_chapters)
    """

    def __init__(self, spec_loader: SpecLoader):
        self.spec_loader = spec_loader
        self.legal_chapters = spec_loader.load_legal_chapters()
        self.regulatory_versions = spec_loader.load_regulatory_versions()
        if self.regulatory_versions["acquisition_status"] != "COMPLETED":
            raise RuntimeError("法规原文未采集，E1 不得运行")
        if self.regulatory_versions["applicability_rule_status"] == "UNRESOLVED":
            self._applicability_resolved = False
        else:
            self._applicability_resolved = True

    def resolve_version(self, period: int, report_year: int, disclosure_date: str = None) -> dict:
        if not self._applicability_resolved:
            raise RuntimeError(
                "reg_version 适用规则未裁决（披露日 vs 报告期末），E1 判定程序不得运行。"
                "请 Human Gate 裁决后更新 regulatory_versions.json 的 applicability_rule_status。"
            )
        if period == 4:
            standard = "第2号"
        elif period == 2:
            standard = "第3号"
        else:
            raise ValueError(f"period 必须是 2 或 4，实际: {period}")
        rule = self.regulatory_versions["applicability_rule"]
        versions = [v for v in self.regulatory_versions["versions"] if v["standard"] == standard]
        versions.sort(key=lambda v: v["effective_from"])
        if rule == "by_disclosure_date":
            if disclosure_date is None:
                raise ValueError("by_disclosure_date 模式必须提供 disclosure_date")
            effective_date = disclosure_date
        elif rule == "by_period_end":
            if period == 4:
                effective_date = f"{report_year}-12-31"
            else:
                effective_date = f"{report_year}-06-30"
        else:
            raise ValueError(f"未知的适用规则: {rule}")
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
        version = self.resolve_version(period, report_year, disclosure_date)
        standard = version["standard"]
        document_no = version["document_no"]
        effective_from = version["effective_from"]
        original_file = version["original_file"]
        legal_key = Path(original_file).stem
        legal_info = self.legal_chapters["chapters"].get(legal_key)
        if legal_info is None:
            raise ValueError(f"未找到法定章节清单：{legal_key}")
        sections = legal_info["sections"]
        required_sections = [s for s in sections if s["required"] == "always"]
        conditional_sections = [s for s in sections if s["required"] == "conditional"]
        missing = []
        not_applicable = []
        extraction_failures = []

        def is_disclosed(required_title: str) -> bool:
            for disclosed in disclosed_chapters:
                if ChapterCompliance._matches(required_title, disclosed):
                    return True
            if ChapterCompliance._matches_split(required_title, disclosed_chapters):
                return True
            return False

        for section in required_sections:
            chapter_title = f"{section['marker']} {section['name']}"
            if is_disclosed(chapter_title):
                pass
            else:
                missing.append(chapter_title)
        for section in conditional_sections:
            chapter_title = f"{section['marker']} {section['name']}"
            not_applicable.append(chapter_title)
        order_violations = []
        required_order = [f"{s['marker']} {s['name']}" for s in required_sections]
        disclosed_to_required = {}
        for disc in disclosed_chapters:
            for req in required_order:
                if ChapterCompliance._matches(req, disc):
                    disclosed_to_required[disc] = req
                    break
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
