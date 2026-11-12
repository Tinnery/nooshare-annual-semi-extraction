"""nooshare-annual-semi-extraction: A 股年报/半年报 MD 内容抽取与特征矩阵生产。

上游 nooshare-annual-semi 产出完备性证明过的 MD 语料，本 package 在此基础上
做章节合规 / 句子级 segmentation / 金融情感 / 表格对账 / forward-looking 抽取，
产出四元 hash 锚定的特征矩阵。
"""

__version__ = "0.1.0"
