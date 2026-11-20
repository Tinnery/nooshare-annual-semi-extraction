"""H2 二级标题内容抽取模块。

目标：从 A 股年报/半年报中提取"第二节"的完整内容。

法规依据：
- 证监会《公开发行证券的公司信息披露内容与格式准则第 2 号》
- "第二节 公司简介和主要财务指标" 是法规要求的关键章节

抽取逻辑：
1. 定位"第二节"标记（支持多种变体：第二节、第2节、第二节等）
2. 提取从"第二节"开始到"第三节"之前的所有内容
3. 输出包含标题、正文、行号范围的结构化数据
"""

from .extractor import extract_h2, extract_h2_batch
from .pattern_loader import H2PatternLibrary, get_h2_library, normalize_for_match

__all__ = [
    "extract_h2",
    "extract_h2_batch",
    "H2PatternLibrary",
    "get_h2_library",
    "normalize_for_match",
]
