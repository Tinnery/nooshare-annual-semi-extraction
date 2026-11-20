"""H2 模板库加载与二级标题识别单测：纯逻辑 + 注入通道，不连 PG。"""

import pytest

from annual_semi_extraction.h2.pattern_loader import (
    H2PatternLibrary,
    normalize_for_match,
)
from annual_semi_extraction.h2.extractor import extract_h2


LIB = [
    {"heading_normalized": "货币资金", "heading_raw": "1、货币资金",
     "heading_level": 2, "count": 40000, "stability_score": 1.0},
    {"heading_normalized": "应收账款", "heading_raw": "3、应收账款",
     "heading_level": 2, "count": 38000, "stability_score": 1.0},
    {"heading_normalized": "提取一般风险准备", "heading_raw": "2．提取一般风险准备",
     "heading_level": 2, "count": 12000, "stability_score": 0.9},
]


def make_lib() -> H2PatternLibrary:
    return H2PatternLibrary(LIB)


class TestNormalize:
    """归一化必须与上游构建脚本 normalize_heading 同语义。"""

    def test_merges_numbered_variants(self):
        assert normalize_for_match("1、货币资金") == "货币资金"
        assert normalize_for_match("1、 货币资金") == "货币资金"   # 全部空白删除
        assert normalize_for_match("2．货币资金：") == "货币资金"
        assert normalize_for_match("（一）货币资金") == "货币资金"
        assert normalize_for_match("货币资金") == "货币资金"

    def test_strips_nested_ordinals(self):
        assert normalize_for_match("（一）1、货币资金") == "货币资金"

    def test_keeps_content_headings(self):
        assert normalize_for_match("2019年年度报告") == "2019年年度报告"
        assert normalize_for_match("货币资金及等价物") == "货币资金及等价物"

    def test_empty(self):
        assert normalize_for_match("") == ""
        assert normalize_for_match("   ") == ""


class TestLookup:
    def test_exact(self):
        hit = make_lib().lookup("2、货币资金")
        assert hit is not None
        assert hit["relation"] == "exact"
        assert hit["heading_normalized"] == "货币资金"
        assert hit["count"] == 40000
        assert hit["candidate_normalized"] == "货币资金"

    def test_glued_prefix_digits(self):
        hit = make_lib().lookup("货币资金 4,342,156.00")
        assert hit is not None
        assert hit["relation"] == "glued_prefix"
        assert hit["heading_normalized"] == "货币资金"

    def test_glued_prefix_rejects_cjk_remainder(self):
        # 剩余部分含汉字 → 不是粘连，是另一个标题，宁缺毋滥
        assert make_lib().lookup("货币资金及等价物") is None

    def test_miss(self):
        lib = make_lib()
        assert lib.lookup("完全不相干的内容标题") is None
        assert lib.lookup("444.59 2.05% 600 否") is None

    def test_empty_candidate(self):
        assert make_lib().lookup("　") is None


class TestDegrade:
    def test_no_env_degrades(self, monkeypatch):
        monkeypatch.delenv("PG_HOST", raising=False)
        lib = H2PatternLibrary()  # 无注入、无 PG 环境变量
        assert lib.lookup("货币资金") is None
        assert lib.load_error == "H2_LIB_NO_PG_ENV"
        assert lib.title_count == 0


MD_SAMPLE = """# 2024 年年度报告

## 第二节 公司简介和主要财务指标

## 1、货币资金 4,342,156.00
存款说明如下……

## 444.59 2.05% 600 否
表格污染行

## 3、应收账款
按账龄披露……

## 第三节 管理层讨论与分析
"""


class TestExtractorIntegration:
    def _write_md(self, tmp_path) -> object:
        d = tmp_path / "published" / "000001"
        d.mkdir(parents=True)
        p = d / "000001_2024_4.md"
        p.write_text(MD_SAMPLE, encoding="utf-8")
        return p

    def test_sub_headings_matched(self, tmp_path):
        p = self._write_md(tmp_path)
        result = extract_h2(p, library=make_lib())
        assert result is not None
        assert result["h2_found"] is True

        subs = result["h2_sub_headings"]
        # 区间内 3 个候选：货币资金(粘连数字)、表格污染行、应收账款
        # 「第二节」「第三节」标记不算候选
        assert len(subs) == 3
        assert all("第" not in s["raw"][:2] or not s["raw"].startswith("第") for s in subs)

        matched = [s for s in subs if s["matched"]]
        assert len(matched) == 2
        norms = {s["match"]["heading_normalized"] for s in matched}
        assert norms == {"货币资金", "应收账款"}

        rejected = [s for s in subs if not s["matched"]]
        assert len(rejected) == 1
        assert rejected[0]["raw"].startswith("444.59")

        assert result["n_sub_headings"] == 3
        assert result["n_sub_matched"] == 2

    def test_degrade_all_unmatched(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PG_HOST", raising=False)
        p = self._write_md(tmp_path)
        result = extract_h2(p)  # 无注入、无 PG → 空库降级，抽取本身不受阻
        assert result["h2_found"] is True
        assert result["n_sub_headings"] == 3
        assert result["n_sub_matched"] == 0
        assert all(s["match"] is None for s in result["h2_sub_headings"])

    def test_line_numbers_absolute(self, tmp_path):
        p = self._write_md(tmp_path)
        result = extract_h2(p, library=make_lib())
        subs = result["h2_sub_headings"]
        # 行号应为文件内绝对行号且落在第二节区间内
        assert result["h2_start_line"] <= min(s["line_no"] for s in subs)
        assert max(s["line_no"] for s in subs) < result["h2_end_line"]
