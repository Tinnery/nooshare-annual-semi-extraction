# nooshare-annual-semi-extraction

A 股年报/半年报 MD 内容抽取与特征矩阵生产。

## 定位

上游 `nooshare-annual-semi` 产出完备性证明过的 MD 语料（交付表 `reconciled_report` + RustFS 桶，sha 锚定，gate_fail=false），本仓库在此基础上进行：

- 章节合规（对齐证监会 §2 号准则**当年版本**）
- 句子级 segmentation + cohort z-score（申万行业 × 年份固定效应）
- 金融情感特征（LM-2011 中文词典 + 语料衍生词典双轨）
- 表格 → DataFrame → 报表项目 canonical → 外部量化 DB 对账
- forward-looking 语句双通道抽取（规则 + LLM）
- 特征矩阵四元 hash 锚（输入 sha + 词典版本 + 分词器 + 管线 commit）

## 取数契约（铁律）

**只走 PG 交付表 + RustFS GET，禁止直连 /backup**（上游 backup_first 只读边界）。

```python
# 取数示例
from annual_semi_extraction.upstream import load_delivered
for slot in load_delivered(year=2024, period=4):
    md_bytes = slot.get_md()  # RustFS GET by winner_md_path
    assert slot.sha256 == sha256(md_bytes)  # sha 锚定校验
```

## Quick Start

```bash
uv venv && uv sync
uv run nooshare-annual-semi-extraction --help
uv run pytest
```

## 架构

```
CLI (Typer) → Tasks → Units (chapter / sentence / sentiment / table / forward)
              + common (canonical_schema §2号准则版本时间轴 / cohort / upstream)
              → 特征矩阵 (四元 hash 锚 + DVC 版本化)
```

## 冻结需求

`deliverables/01-requirement.md`（v2）—— R'0-R'9 + 6 个外部客观标准，本 repo 的**唯一需求权威**。

规格登记表（机器可读，sha256 锚定、测试校验）：

- `annual_semi_extraction/spec/anchors.json` —— E1-E6 锚身份、判定程序、失败分类、授权/禁止数据源
- `annual_semi_extraction/spec/regulatory_versions.json` —— 年报第2号 / 半年报第3号版本时间轴
- `deliverables/05-consumer-contract.md` —— 消费者与维护规则契约

`deliverables/02`、`03`、`04` 为执行参考 / 变更归档，**非需求权威**；其中 R'' / R''' 编号、另一套 E1-E6 语义、Phase 1 结构丢失诊断、源 HTML / trash 恢复条款均已由 01 v2 §四裁定作废。
