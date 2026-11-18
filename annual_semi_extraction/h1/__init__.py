"""H1 一级章节标题抽取模块。

职责：从 A 股年报/半年报 Markdown 文件中抽取一级章节标题，对齐法定章节结构。

输入：Markdown 文件路径
输出：结构化标题列表（含原文、字节偏移、规范化名称）
"""

from .extractor import extract, extract_batch
from .normalizer import normalize_report
from .morphology import classify_h1, LEGAL_NAMES
from .corpus import extract_one as corpus_extract_one

__all__ = [
    "extract",
    "extract_batch",
    "normalize_report",
    "classify_h1",
    "LEGAL_NAMES",
    "corpus_extract_one",
]
