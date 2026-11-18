"""E1 章节合规判定 Unit。

职责：根据法规版本和法定章节清单，判定报告的章节合规性。

契约：
- 输入：报告年份、期别、抽取的标题列表
- 输出：合规判定结果（complete/partial/missing）
- 依赖：spec 子包的规格加载器
- 副作用：无
"""

from .judge import E1Judge, ChapterCompliance, MissingState

__all__ = ["E1Judge", "ChapterCompliance", "MissingState"]
