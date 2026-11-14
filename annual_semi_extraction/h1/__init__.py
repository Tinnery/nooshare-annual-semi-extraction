"""H1 一级章节标题抽取 Unit。

职责：从 A 股年报/半年报 MD 文件中抽取一级章节标题，对齐法定章节结构。

契约：
- 输入：MD 文件路径
- 输出：结构化标题列表（含 verbatim、byte offset、canonical 映射）
- 依赖：上游 nooshare-annual-semi 的 heading_verify 模块
- 副作用：无（纯函数式）
"""

from .extractor import extract, extract_batch
from .normalizer import normalize_report
from .morphology import classify_h1, LEGAL_NAMES
from .corpus import extract_one as corpus_extract_one
from .frozen_judge import FrozenJudge, get_judge

__all__ = [
    "extract",
    "extract_batch",
    "normalize_report",
    "classify_h1",
    "LEGAL_NAMES",
    "corpus_extract_one",
    "FrozenJudge",
    "get_judge",
]
