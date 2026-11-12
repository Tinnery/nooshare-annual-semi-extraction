"""nooshare-annual-semi-extraction 冻结需求（v1）。

> 本文件是本 repo 的唯一需求权威。源自 nooshare-annual-semi 主理人 2026-11-13 落盘的
> `deliverables/04-extraction-requirement.md`，作为本 repo req-analyst 的输入。
> 任何偏离须经 solution-architect 走变更流程并同步全部受影响方。

## 一、身份与上下游

- **Repo**: `nooshare-annual-semi-extraction`（package: `annual_semi_extraction`）
- **上游**: `nooshare-annual-semi`（语料生产 + 完备性证明，已封版，proof.json gate_fail=false）
- **取数契约**: PG 交付表（`annual_semi.reconciled_report`: slot → winner_md_path → 桶键 → sha256）+ RustFS GET。**禁止直连 /backup**。
- **一期范围**: R'0-R'6（特征/矩阵生产，确定性、可复现）
- **二期范围**: R'7-R'9（研究验证）——届时可拆 `nooshare-annual-semi-research` 独立 repo

## 二、外部客观标准（6 个，全部机器/监管可判）

| # | 标准 | 判定方式 |
|---|---|---|
| E1 | 章节完备性 = §2 号准则**当年版本** | 缺节打监管违规 flag，可被交易所问询函印证 |
| E2 | 表格抽取正确率 = 与东方财富/同花顺量化 DB 逐项对账 | 误差 ≤0.5% 或绝对差 ≤1 元 |
| E3 | 情感/语气信号有效性 = 与未来业绩相关性 | forward-looking 语气 → 下期 ROE/营收增长率方向预测 ≥60% 准确率 |
| E4 | 可复现性 = byte-identical 重跑 | 同 sha 输入 + 同词典版本 + 同分词器 → 同特征矩阵 hash |
| E5 | 缺失机制 = Heckman λ 显著性 / 非随机性描述报告 | 1,688 unobtainable 的非随机性量化 |
| E6 | 监管印证 = 问询函对齐 | 模型判"高风险/前瞻模糊"样本下一年被问询函覆盖比例显著高于基线（卡方 p<0.05） |

## 三、冻结需求 R'0-R'9

> **R'0** 论域 = nooshare-annual-semi 交付表（2018+，72,705 MD，sha 锚定）+ §2 号准则版本时间轴 + 申万行业历史分类。取数只走交付表 + RustFS，禁止直连 /backup。

> **R'1** 章节 schema 对齐 §2 号准则**当年版本**；每报告输出 `chapter_compliance` 矩阵（10 节 × 命中/缺失/字数），缺节打监管违规 flag（E1）。

> **R'2** 句子级最小分析单元；任何文本特征必须同时输出 cohort（申万行业 × 年份）内 z-score 与原始值。

> **R'3** 情感/语气用 LM-2011 中文金融词典 + 自建年报语料 TF-IDF 衍生词典双轨；禁用通用 Hownet/NTUSD 作为主信号。

> **R'4** 表格 → DataFrame → 报表项目 canonical 化 → 与东方财富/同花顺量化 DB 逐项对账，误差 ≤0.5% 或 ≤1 元；对账失败进 evidence 表，不静默丢弃（E2）。

> **R'5** forward-looking 语句双通道抽取（规则初筛 + LLM 复核），单独建子语料与子特征矩阵。

> **R'6** 特征矩阵带四元 hash 锚（输入 MD sha set + 词典版本 + 分词器版本 + 管线 commit）；DVC 版本化；同输入同版本 byte-identical 重跑可证（E4）。

> **R'7**（二期）缺失机制显式建模：1,688 unobtainable 进样本描述统计；用特征做回归时必须报告 Heckman 两步或等价校正（E5）。

> **R'8**（二期）信号有效性硬门禁：任何特征入主矩阵前必须证明与未来业绩（下期 ROE/营收增长率方向）相关 ≥60% 准确率（E3）。

> **R'9**（二期）监管印证抽检：模型判"高风险/前瞻模糊"样本下一年被问询函覆盖比例显著高于基线（卡方 p<0.05）（E6）。

---

**对抗失控的根因机制**：spec-driven + 外部锚 gate。每个 R 绑一个外部客观标准，"做出来了"不算交付，"对得上外部锚"才算数。
