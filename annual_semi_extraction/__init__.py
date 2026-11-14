"""nooshare-annual-semi-extraction: A 股年报/半年报 MD 内容抽取与特征矩阵生产。

架构遵循 CLI → Task → Units 模式（Pattern 1: CLI-driven Application）：
- cli.py: 薄 CLI 层，仅解析参数、调用 Task
- h1/: H1 标题抽取管线（extractor / normalizer / morphology / corpus / numbering / frozen_judge）
- e1/: E1 章节合规判定（judge）
- spec/: 规格加载器（loader）

上游 nooshare-annual-semi 产出完备性证明过的 MD 语料，本 package 在此基础上
做章节合规 / 句子级 segmentation / 金融情感 / 表格对账 / forward-looking 抽取，
产出四元 hash 锚定的特征矩阵。
"""

__version__ = "0.2.0"
