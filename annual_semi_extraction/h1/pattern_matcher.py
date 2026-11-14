"""H1 Pattern Matcher — 从标准库匹配标题组合，避免贪心匹配正文。

核心思路：
1. 提取 headings 后，构建 raw_pattern（可能包含贪心污染的标题）
2. 先尝试匹配标准库（精确 hash 或模糊前缀匹配）
3. 命中 → 用库里的 canonical_name 替换，不贪心
4. 未命中 → 保持现有逻辑不变

用法：
    from .pattern_matcher import get_pattern_matcher
    matcher = get_pattern_matcher()
    lib = matcher.match(raw_pattern)
    if lib:
        # lib['headings'] 包含 {ordinal, raw_name, canonical_name}
        # 用 lib 的 canonical_name 替换提取结果的 canonical_name
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

# PostgreSQL 连接参数
PG_CONFIG = dict(
    host='pg.pro.neuralj.com',
    port=5432,
    dbname='nooshare_dev',
    user='travis',
    password='sheeta-pg'
)

# 尾部噪声正则（点线、页码、省略号等）
RE_TRAIL_NOISE = re.compile(r'[\.…·─—─\s\d]{2,}$')


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
    """从 PG 加载标准库 pattern，支持精确匹配和模糊前缀匹配。"""

    def __init__(self):
        self._patterns: dict[str, dict] = {}  # hash -> {pattern, count, headings}
        self._loaded = False
        self._load_error: Optional[str] = None

    def _load(self):
        """懒加载：从 PG 读取标准库。"""
        if self._loaded:
            return
        try:
            import psycopg2
            conn = psycopg2.connect(**PG_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                SELECT pattern_hash, pattern, count, headings
                FROM annual_semi.h1_pattern_library
                ORDER BY count DESC
            """)
            rows = cur.fetchall()
            for row in rows:
                phash, pattern, count, headings = row
                self._patterns[phash] = {
                    "pattern": pattern,
                    "count": count,
                    "headings": headings,
                }
            cur.close()
            conn.close()
            self._loaded = True
        except Exception as e:
            self._load_error = str(e)
            self._loaded = True  # 标记为已尝试，避免重复失败

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


# 全局单例
_matcher: Optional[PatternMatcher] = None


def get_pattern_matcher() -> PatternMatcher:
    """获取全局 PatternMatcher 单例。"""
    global _matcher
    if _matcher is None:
        _matcher = PatternMatcher()
    return _matcher
