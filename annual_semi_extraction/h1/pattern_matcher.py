"""H1 Pattern Matcher — 从标准库匹配标题组合，避免贪心匹配正文。

模板库权威来源：PostgreSQL `annual_semi.h1_pattern_library`
（全量抽取后累积的标准标题组合，含 count 命中统计）。

加载优先级：
1. 显式注入的 patterns dict（单元测试 mock 通道）
2. 环境变量配置的 PG 连接（PG_HOST / PG_PORT / PG_NAME / PG_USER / PG_PASSWORD）
3. 均未配置或连接失败 → 空匹配器降级（is_standard_title / anchor_title / match 空转）

用法：
    from .pattern_matcher import get_pattern_matcher
    matcher = get_pattern_matcher()          # 运行时：读 PG，未配置则降级
    matcher = get_pattern_matcher(patterns)  # 测试：注入假库
    lib = matcher.match(raw_pattern)
    if lib:
        # lib['headings'] 包含 {ordinal, raw_name, canonical_name}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

# 尾部噪声正则（点线、页码、省略号等）
RE_TRAIL_NOISE = re.compile(r'[\.…·─—─\s\d]{2,}$')

# 模板库表（schema 固定）
LIBRARY_TABLE = "annual_semi.h1_pattern_library"


def _strip_trailing_noise(name: str) -> str:
    """去除标题尾部噪声（点线、页码等）。"""
    return RE_TRAIL_NOISE.sub("", name).strip()


def _normalize_heading(name: str) -> str:
    """标准化单个标题文本：去尾部噪声。不做长度截断。"""
    if not name:
        return ""
    return _strip_trailing_noise(name)


def _normalize_pattern(pattern: list[str]) -> tuple[str, ...]:
    """标准化整个 pattern：对每个 heading 做 normalize。"""
    return tuple(_normalize_heading(h) for h in pattern)


def _pattern_hash(normalized: tuple[str, ...]) -> str:
    """计算标准化 pattern 的 SHA256 哈希。"""
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False).encode()).hexdigest()


class PatternMatcher:
    """从标准库加载 pattern，支持精确匹配、模糊前缀匹配与标题级锚定。

    标准库来源优先级：显式注入 > PG 环境变量 > 空降级。
    """

    def __init__(self, patterns: Optional[dict[str, dict]] = None):
        self._patterns: dict[str, dict] = {}  # hash -> {pattern, count, headings}
        self._titles: list[str] = []         # 所有标准标题，按长度降序（最长优先）
        self._title_set: set[str] = set()    # O(1) 判定「本身已是标准标题」
        self._loaded = False
        self._load_error: Optional[str] = None
        self._injected = patterns

    def _ingest(self, patterns: dict[str, dict]) -> None:
        """把 {hash -> {pattern, count, headings}} 装载进内部索引并构建标题集。"""
        for phash, data in patterns.items():
            self._patterns[phash] = {
                "pattern": data.get("pattern", []),
                "count": data.get("count", 0),
                "headings": data.get("headings", []),
            }

        # 构建「标准标题」集合，两个权威来源，均非手敲关键词：
        #   1. 标准库：pattern 数组 + headings 的 raw_name / canonical_name
        #   2. 法规有限集：legal_chapters.json（morphology.legal_name_set，
        #      仓库铁律指定的外部有限集）
        titles: set[str] = set()
        for data in self._patterns.values():
            for t in data["pattern"] or []:
                if t and t.strip():
                    titles.add(t.strip())
            for h in data.get("headings") or []:
                for k in ("raw_name", "canonical_name"):
                    v = h.get(k) if isinstance(h, dict) else None
                    if v and v.strip():
                        titles.add(v.strip())
        try:
            from .morphology import LEGAL_NAMES
            titles.update(t.strip() for t in LEGAL_NAMES if t and t.strip())
        except Exception:
            pass  # 法规集不可用时仍可用标准库标题，降级而非失败

        self._title_set = titles
        # 长标题优先，避免「重要提示、目录和释义」被短标题「释义」误截；
        # 同长度用字典序 tie-break，保证跨进程（PYTHONHASHSEED 不同）一致。
        self._titles = sorted(titles, key=lambda t: (-len(t), t))

    def _load(self):
        """懒加载：注入通道 > PG 环境变量 > 空降级。"""
        if self._loaded:
            return

        if self._injected is not None:
            self._ingest(self._injected)
            self._loaded = True
            return

        host = os.environ.get("PG_HOST", "").strip()
        if not host:
            self._load_error = (
                "PG_HOST 未配置：模板库不可用，"
                "标题锚定与库匹配降级为空匹配"
            )
            self._loaded = True
            return

        try:
            import psycopg2

            conn = psycopg2.connect(
                host=host,
                port=int(os.environ.get("PG_PORT", "5432")),
                dbname=os.environ.get("PG_NAME", "").strip(),
                user=os.environ.get("PG_USER", "").strip(),
                password=os.environ.get("PG_PASSWORD", ""),
                connect_timeout=5,
                sslmode="disable",  # stunnel 是 TCP 代理，强制明文连接
            )
            cur = conn.cursor()
            cur.execute(
                f"SELECT pattern_hash, pattern, count, headings "
                f"FROM {LIBRARY_TABLE} ORDER BY count DESC"
            )
            rows: dict[str, dict] = {}
            for phash, pattern, count, headings in cur.fetchall():
                rows[phash] = {"pattern": pattern, "count": count, "headings": headings}
            cur.close()
            conn.close()
            self._ingest(rows)
            self._loaded = True
        except Exception as e:
            self._load_error = str(e)
            self._loaded = True  # 标记为已尝试，避免重复失败；降级为空匹配

    @property
    def title_count(self) -> int:
        """标准标题词条数（供 fail-fast / 诊断使用）。"""
        self._load()
        return len(self._title_set)

    def is_standard_title(self, name: str) -> bool:
        """该文本本身就是标准库里的标题（用于 canonical_name 兜底）。"""
        self._load()
        if self._load_error or not name:
            return False
        return name.strip() in self._title_set

    def anchor_title(self, raw_name: str) -> Optional[str]:
        """标题级锚定：标准库已有的标题，抽取时即中止贪心。

        若 raw_name 本身是标准标题 → 返回 None（不动）。
        若 raw_name 以某个标准标题开头、后面粘了正文/点线/噪声等
        多余内容 → 返回该标准标题（取最长匹配），调用方据此回写 raw_name。
        标准库不可用或无命中 → 返回 None（保持原有贪心结果，不破坏兜底）。

        例：
            「释义在本报告书中，除非文义另有所指…」 → 「释义」
            「重要提示、目录和释义公司董事会…」     → 「重要提示、目录和释义」
            「公司业务概要........................」  → 「公司业务概要」
        """
        self._load()
        if self._load_error or not raw_name:
            return None
        s = raw_name.strip()
        if not s or s in self._title_set:
            return None

        # 先剥离转换残留（TOC 点线 / 页码 / 勾选框）。必须先去噪再匹配，
        # 否则「财务会计报告（未经审计）......」会被原样前缀匹配截成
        # 「财务会计报告」，丢掉合法限定语。
        try:
            from .morphology import _strip_noise
            clean, tags = _strip_noise(s)
        except Exception:
            clean, tags = s, []
        clean = clean.strip()
        target = clean if (tags and clean and clean != s) else s
        if not target:
            return None
        if target in self._title_set:
            return target

        # 最长前缀匹配：标准标题后粘了正文 / 目录点线时截断到标准标题
        for title in self._titles:
            if len(title) < len(target) and target.startswith(title):
                rest = target[len(title):].strip()
                # 合法限定语（如「（未经审计）」「(续)」）不是贪心污染，
                # 保留完整标题，只去掉点线噪声。
                if re.fullmatch(r"[（(][^）)]{1,16}[）)]", rest):
                    return target
                return title

        # 形态清洗兜底：命中 TOC 点线 / 页码等转换残留，去噪后是一个
        # 短而干净的标题（可能是有限集未收录的合法变体，如
        # 「董事、监事和高级管理人员情况」「公司债相关情况」），直接返回
        # 去噪结果。不引入任何手敲关键词；verbatim 仍原样保留。
        if tags and clean and clean != s:
            if (len(clean) <= 24
                    and not re.search(r"[，。；：？！,;:?!]", clean)
                    and not re.search(r"\d{1,4}\s*$", clean)):
                return clean
        # 未命中任何标准标题且非形态噪声：不动，交给人工排查
        return None

    def match(self, raw_pattern: list[str]) -> Optional[dict]:
        """尝试匹配 raw_pattern 到标准库。

        策略1：精确匹配 — normalize 后 hash 精确命中
        策略2：模糊前缀匹配 — 库标题是 raw 标题的前缀（处理贪心吞入正文）

        Args:
            raw_pattern: 原始标题文本列表（来自 MD 文件提取的 raw_name 序列）

        Returns:
            如果匹配成功，返回 {"pattern", "count", "headings"}；
            否则返回 None。
        """
        self._load()
        if self._load_error:
            return None

        if not raw_pattern:
            return None

        # 策略1：精确匹配（normalize 后 hash）
        normalized = _normalize_pattern(raw_pattern)
        phash = _pattern_hash(normalized)
        if phash in self._patterns:
            return self._patterns[phash]

        # 策略2：模糊前缀匹配
        # 当 raw 标题被贪心吞入正文时（如 "重要提示...公司董事会..."），
        # 库标题 "重要提示、目录和释义" 是 raw 标题的前缀
        # 允许 raw_pattern 比库 pattern 长（raw 可能有额外标题）
        best_match = None
        best_score = 0.0

        for lib_hash, lib_data in self._patterns.items():
            lib_pattern = lib_data["pattern"]
            if len(lib_pattern) > len(raw_pattern):
                continue  # 库比 raw 长，不可能匹配

            # 尝试将库 pattern 对齐到 raw pattern 的每个起始位置
            for start in range(len(raw_pattern) - len(lib_pattern) + 1):
                prefix_matches = 0
                for j, lib_title in enumerate(lib_pattern):
                    raw_title = raw_pattern[start + j]
                    if raw_title.startswith(lib_title):
                        prefix_matches += 1
                    elif _normalize_heading(raw_title) == lib_title:
                        prefix_matches += 1

                score = prefix_matches / len(lib_pattern)
                if score > best_score:
                    best_score = score
                    best_match = lib_data
                if score >= 1.0:
                    break  # 完美匹配，无需继续
            if best_score >= 1.0:
                break

        # 阈值：至少 80% 的标题匹配才算命中
        if best_score >= 0.8 and best_match is not None:
            return best_match

        return None

    @property
    def is_available(self) -> bool:
        """标准库是否可用。"""
        self._load()
        return self._loaded and self._load_error is None

    @property
    def size(self) -> int:
        """标准库中的 pattern 数量。"""
        self._load()
        return len(self._patterns)

    @property
    def load_error(self) -> Optional[str]:
        """加载失败原因（未配置 / 连接失败 / 解析失败），None 表示正常。"""
        self._load()
        return self._load_error


# 全局单例（按注入内容缓存；None = 运行时 PG 模式）
_matchers: dict[tuple, PatternMatcher] = {}
_RUNTIME_KEY: tuple = ("runtime",)


def get_pattern_matcher(patterns: Optional[dict[str, dict]] = None) -> PatternMatcher:
    """获取 PatternMatcher 实例。

    Args:
        patterns: 显式注入的标准库（单元测试 mock 通道）。
                  None 表示运行时模式：按环境变量连 PG，未配置则降级。

    Returns:
        PatternMatcher 实例
    """
    key = _RUNTIME_KEY if patterns is None else ("injected", id(patterns))
    if key not in _matchers:
        _matchers[key] = PatternMatcher(patterns)
    return _matchers[key]
