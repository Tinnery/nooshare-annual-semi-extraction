"""PatternMatcher 测试：注入通道、运行时降级通道、匹配策略。

不依赖真实 PG：注入通道用假库；运行时通道在未配置 PG_HOST 时
验证降级行为（空匹配器、is_standard_title/anchor_title/match 空转）。
"""

import pytest

from annual_semi_extraction.h1.pattern_matcher import (
    PatternMatcher,
    _normalize_pattern,
    _pattern_hash,
    get_pattern_matcher,
)


# ── 测试用假库：一条标准 pattern + headings ──────────────────────────

FAKE_HEADINGS = [
    {"ordinal": 1, "raw_name": "重要提示、目录和释义", "canonical_name": "重要提示、目录和释义"},
    {"ordinal": 2, "raw_name": "公司简介和主要财务指标", "canonical_name": "公司简介和主要财务指标"},
    {"ordinal": 3, "raw_name": "管理层讨论与分析", "canonical_name": "管理层讨论与分析"},
]

def _fake_library() -> dict[str, dict]:
    normalized = _normalize_pattern(list(FAKE_HEADINGS[i]["raw_name"] for i in range(3)))
    phash = _pattern_hash(normalized)
    return {
        phash: {"pattern": list(normalized), "count": 10858, "headings": FAKE_HEADINGS},
    }


class TestInjectedChannel:
    """显式注入通道：单元测试 mock 标准库。"""

    def test_injected_match_exact(self):
        matcher = PatternMatcher(_fake_library())
        assert matcher.is_available
        assert matcher.size == 1

        raw = ["重要提示、目录和释义", "公司简介和主要财务指标", "管理层讨论与分析"]
        hit = matcher.match(raw)
        assert hit is not None
        assert hit["count"] == 10858
        assert hit["headings"][0]["canonical_name"] == "重要提示、目录和释义"

    def test_injected_match_fuzzy_prefix(self):
        """贪心污染标题（尾部粘正文）走模糊前缀匹配。"""
        matcher = PatternMatcher(_fake_library())
        raw = [
            "重要提示、目录和释义公司董事会在本报告中",
            "公司简介和主要财务指标",
            "管理层讨论与分析",
        ]
        hit = matcher.match(raw)
        assert hit is not None

    def test_injected_is_standard_title(self):
        matcher = PatternMatcher(_fake_library())
        assert matcher.is_standard_title("管理层讨论与分析")
        assert not matcher.is_standard_title("某个不存在的标题")

    def test_injected_anchor_title_greedy_cut(self):
        """标准标题后粘正文 → 截断回标准标题。"""
        matcher = PatternMatcher(_fake_library())
        anchored = matcher.anchor_title("重要提示、目录和释义公司董事会")
        assert anchored == "重要提示、目录和释义"

    def test_injected_anchor_title_clean_untouched(self):
        """本身已是标准标题 → 不动。"""
        matcher = PatternMatcher(_fake_library())
        assert matcher.anchor_title("管理层讨论与分析") is None

    def test_injected_merges_legal_names(self):
        """标题集并入法规有限集（morphology.LEGAL_NAMES）。"""
        matcher = PatternMatcher(_fake_library())
        # 财务报告 来自 legal_chapters.json 法规集，不在假库里
        assert matcher.title_count > len(_fake_library()) * 3


class TestRuntimeDegradeChannel:
    """运行时通道：未配置 PG 环境变量 → 空匹配器降级。"""

    @pytest.fixture(autouse=True)
    def _no_pg_env(self, monkeypatch):
        """确保测试进程内无 PG 配置（CI 环境同样成立）。"""
        for var in ("PG_HOST", "PG_PORT", "PG_NAME", "PG_USER", "PG_PASSWORD"):
            monkeypatch.delenv(var, raising=False)

    def test_unconfigured_degrades_to_empty(self):
        matcher = PatternMatcher()
        assert not matcher.is_available
        assert matcher.size == 0
        assert matcher.title_count == 0
        assert "PG_HOST" in (matcher.load_error or "")

    def test_unconfigured_match_returns_none(self):
        matcher = PatternMatcher()
        assert matcher.match(["管理层讨论与分析"]) is None
        assert matcher.anchor_title("重要提示、目录和释义公司董事会") is None
        assert not matcher.is_standard_title("管理层讨论与分析")

    def test_get_pattern_matcher_runtime_singleton(self):
        """运行时模式单例稳定，注入模式按内容独立。"""
        m1 = get_pattern_matcher()
        m2 = get_pattern_matcher()
        assert m1 is m2

        fake = _fake_library()
        m3 = get_pattern_matcher(fake)
        m4 = get_pattern_matcher(fake)
        assert m3 is m4
        assert m3 is not m1
        assert m3.is_available  # 注入通道不受运行时降级影响
