# nooshare-annual-semi-extraction 冻结需求 v2

> **本文件是本 repo 的唯一需求权威**（AGENTS.md 铁律 1）。源自 nooshare-annual-semi 主理人 2026-11-13 落盘的
> `deliverables/04-extraction-requirement.md`，作为本 repo req-analyst 的输入。
> **任何后续偏离须经 solution-architect 走变更流程并同步全部受影响方。**
>
> - **v1 基线**：commit `4a61da7` 的 `deliverables/01-requirement.md`（冻结原文，可随时回滚）
> - **v2 变更依据**：`deliverables/04-deep-rewrite-proposal.md` + 用户 2026-11-13 02:22「按照顺序落地需求」指令（Agent mode）
> - **变更性质**：不新增需求条目、不新增 E 编号、**不改 R'0-R'9 编号与 E1-E6 原义**、不改取数边界；只补判定程序、前置条件、禁止项与权威收敛
> - **批准说明**：本次由用户直接批准，变更登记见 §〇；若 solution-architect 流程另有形式要求，应补办登记，不影响本版技术内容
> - **回滚**：`git show 4a61da7:deliverables/01-requirement.md`

---

## 〇、变更登记

| 项 | v1 | v2 | 依据 |
|---|---|---|---|
| 需求编号 | R'0-R'9 | **R'0-R'9（不变）** | 04 §0 |
| E1-E6 语义 | 6 个外部锚 | **原义不变**，补外部身份/判定函数/失败归类 | 04 §4 |
| 锚身份 | 裸标签 `E1`-`E6` | `E{n}@anchors:<sha>:{n}`，注册表 `annual_semi_extraction/spec/anchors.json` | 04 §4 元规则 1 |
| 法规版本 | "§2 号准则当年版本" | 年报第2号 / 半年报第3号**双准则** + 版本函数 + 原文 sha | 04 §2-E |
| 表格裁判 | 量化 DB 单源 | XBRL 实例文档主裁判 + 量化 DB 交叉 + 三表勾稽 | 04 §2-F |
| 可复现 | byte-identical | diff=0 **且** 双路径收敛；第五元锚（归一化/LLM） | 04 §2-H |
| 缺失 | 单一"缺失" | 三态：NOT_APPLICABLE / NOT_DISCLOSED / EXTRACTION_FAILURE | 04 §2-I |
| 取数边界 | 交付表 + RustFS GET | **不变**；源 HTML / trash / `sina_bulletin.db` 明确列为未授权 | 04 §1 |
| 权威文档 | 01 一份 | 仍为 01 一份；02/03/04 降级为执行参考或归档 | 04 §8 |
| 文件首行 | 残缺 `"""` docstring | 修正为 markdown 标题 | 格式瑕疵修正 |
| `reg_version` 适用规则 | 未裁决（`UNRESOLVED`） | **已裁决 `by_period_end`（按报告期末）** | Human Gate 2026-11-13 追认（见下方变更登记 v2.1） |
| E1 gate | `blocked_until` 标注未裁决 | `blocked_until = null`，判定程序解除阻断 | Human Gate 2026-11-13 |

**注册表 sha256 登记**（由 `tests/test_spec.py` 校验；任一注册表变更未同步本处即测试失败，强制走变更流程）：

```
ANCHOR_REGISTRY_SHA256 = cb4aeb67963b5c21dc370a033271c1502c4a8d1718a8231c4a74be4f2f33b135
REGULATORY_VERSIONS_SHA256 = 0fba0f30808bea310aaccf61fea4a3130455ae296fa0335debd675a3c29584d6
LEGAL_CHAPTERS_SHA256 = 6ed45254219cf9867bf18cc7edf3602db2547d11f404667fb86fa06cdd601a6f
```

**变更登记 v2.1**（2026-11-13，Human Gate 批准 `①A`）：
- 用户此前已裁决 `reg_version` 按**报告期末**（`by_period_end`），`regulatory_versions.json` 已置 `RESOLVED` 并登记 5 份法规原文 sha256；但本文件 §〇 的 sha 登记、未决清单、`anchors.json` 的 `blocked_until`、`tests/test_spec.py` 的断言未同步，造成 14 项测试失败与 gate 状态不一致。本次统一补齐，不改 R'0-R'9 编号、不改 E1-E6 原义、不改取数边界。
- 原条款「未裁决前 E1 判定程序不得运行」在裁决前有效，现因前提解除而失效；**保留该表述作为历史条款记录**，不代表当前仍处于阻断状态。

**仍未决、禁止 Agent 自行裁决**：

1. ~~`reg_version` 自变量按**披露日**还是**报告期末**~~ **已解除**（2026-11-13 Human Gate 追认）：适用规则为 **`by_period_end`（按报告期末）**。例：2024 年年报（期末 2024-12-31）适用〔2021〕15号；2025 年年报（期末 2025-12-31）适用〔2025〕3号。原条款「未裁决前 E1 判定程序不得运行」仅在裁决前有效。
2. ~~法规原文 PDF 尚未采集~~ **已解除**（2026-11-13）：5 份 PDF 已从证监会官网下载并登记 sha256，存放于 `annual_semi_extraction/spec/regulatory_texts/`。
3. ~~第3号 2025 修订版文号未核实~~ **已解除**（2026-11-13）：文号为**证监会公告〔2025〕4号**，发布日 2025-03-21，施行日 2025-07-01。
4. 源 HTML / trash 快照 / `sina_bulletin.db` **未授权**纳入取数契约；若需纳入，须 Human Gate 批准并变更本节与 R'0。

---

## 一、身份与上下游（v1 原文）

- **Repo**: `nooshare-annual-semi-extraction`（package: `annual_semi_extraction`）
- **上游**: `nooshare-annual-semi`（语料生产 + 完备性证明，已封版，proof.json gate_fail=false）
- **取数契约**: PG 交付表（`annual_semi.reconciled_report`: slot → winner_md_path → 桶键 → sha256）+ RustFS GET。**禁止直连 /backup**。
- **一期范围**: R'0-R'6（特征/矩阵生产，确定性、可复现）
- **二期范围**: R'7-R'9（研究验证）——届时可拆 `nooshare-annual-semi-research` 独立 repo

---

## 二、外部客观标准（E1-E6，6 个，全部机器/监管可判）

### 2.1 v1 原义（逐字保留，语义不变）

| # | 标准 | 判定方式 |
|---|---|---|
| E1 | 章节完备性 = §2 号准则**当年版本** | 缺节打监管违规 flag，可被交易所问询函印证 |
| E2 | 表格抽取正确率 = 与东方财富/同花顺量化 DB 逐项对账 | 误差 ≤0.5% 或绝对差 ≤1 元 |
| E3 | 情感/语气信号有效性 = 与未来业绩相关性 | forward-looking 语气 → 下期 ROE/营收增长率方向预测 ≥60% 准确率 |
| E4 | 可复现性 = byte-identical 重跑 | 同 sha 输入 + 同词典版本 + 同分词器 → 同特征矩阵 hash |
| E5 | 缺失机制 = Heckman λ 显著性 / 非随机性描述报告 | 1,688 unobtainable 的非随机性量化 |
| E6 | 监管印证 = 问询函对齐 | 模型判"高风险/前瞻模糊"样本下一年被问询函覆盖比例显著高于基线（卡方 p<0.05） |

> **v2 澄清**：v1 表里的"§2 号准则当年版本"在 v2 中按 §2.3 实现为**年报第2号 / 半年报第3号双准则版本函数**——这是判定程序的深化，不是把 E1 换成另一个标准。同理 E2 的量化 DB 仍是原锚，XBRL 是新增的主裁判。

### 2.2 锚身份（元规则 M1）

- 每个锚的不可变身份为 `E{n}@anchors:<sha256(anchors.json)>:{n}`，注册表见 `annual_semi_extraction/spec/anchors.json`。
- **禁止跨文档以裸标签 E1-E6 复用不同语义**。02/03 曾对同名标签给出另一套定义，已在 §七作废。
- 注册表不写自身 sha（避免自指）；sha 登记在本节，由测试校验。

### 2.3 判定程序（每个锚机器可判）

| 锚 | 外部身份 | 判定函数 | 通过条件 | 失败归类 |
|---|---|---|---|---|
| E1 | 第2号/第3号各版文号 + 施行日 + 原文 sha256 | `reg_version(period, disclosure_date)` → 法定章节集；算 missing/extra/order；三态分别计数 | NOT_DISCLOSED 打监管 flag；EXTRACTION_FAILURE 判工程 fail；NOT_APPLICABLE 不计缺失 | 版本选错 / 准则串用 / 三态混计 / 标题误升格 |
| E2 | XBRL 实例文档（主）+ 量化 DB 快照 ID/日期/口径版本 | canonical `(concept, period, scope, unit, value)` → 三表勾稽 → 主对账 → 交叉验证 → 分歧入 evidence 表 | 误差 ≤0.5% 或 ≤1 元；失败不静默丢弃；无 verbatim span 判 fail | 期间/口径/单位/主体错配、跨页断行、LLM 造数 |
| E3 | 下期实际 ROE / 营收增长率 | 时序外检验（t 期特征预测 t+1）+ 行业×年份固定效应 | ≥60% 且显著优于基线 | 前视偏差 / 全样本拟合 / 当前行业分类回填历史 |
| E4 | 四/五元 hash 锚 + 判定程序 commit + 归一化函数版本 | 重跑逐字节比 **且** 双路径收敛 | diff=0 **且** canonical 元组收敛 | 模型/归一化/判定程序未锚定；LLM 进主链路 |
| E5 | 上游 proof.json 的 1,688 清单 + 三态计数 | Heckman 两步或等价校正；分层描述统计 | λ 显著性可报告；NOT_APPLICABLE 不进选择偏差 | 三态混计 / 抽取失败伪装成未披露 |
| E6 | 问询函原文 + 披露日期 + 代码 | 高风险 vs 基线次年覆盖率，卡方；基线构造落盘 | p<0.05 且时间不倒挂 | 时间倒挂 / 挑基线调 p 值 |

**不纳入本 repo 验收**（服务于另一个不存在的 RAG 产品）：Recall@10 / MRR、cell-level 人工录入准确率、Cohen's κ（仅作标注过程质控）、引用覆盖率、多粒度提升 10%。若确需，另立下游 repo 规格，不得覆盖 E1-E6 标签。

### 2.4 元规则

1. **M1 锚身份**：见 §2.2。
2. **M2 可反驳性**：每个 frame 必须能一键回到原文 verbatim span；做不到即判 fail，不进统计分母。
3. **M3 判定程序版本化**：E 的判定函数进 git，其 commit 纳入 hash 锚；换判定程序必须重跑全部 E。

---

## 三、冻结需求 R'0-R'9

> 每条 = `【v1 冻结原句】` + `【v2 深化条款】`。冲突时以 v1 原句为准并走变更流程。

**R'0 论域**：`【v1】` 论域 = nooshare-annual-semi 交付表（2018+，72,705 MD，sha 锚定）+ §2 号准则版本时间轴 + 申万行业历史分类。取数只走交付表 + RustFS，禁止直连 /backup。
`【v2】` ① 论域按 `period ∈ {2,4}` 分别绑定第3号/第2号准则版本；② 版本表为 `reg_version` 函数，产物带原文 sha256（未采集前标 PENDING）；③ 上游 proof.json 与 1,688 unobtainable 清单作为只读证据纳管；④ 见 §四取数边界裁定。

**R'1 章节 schema**：`【v1】` 章节 schema 对齐 §2 号准则**当年版本**；每报告输出 `chapter_compliance` 矩阵（10 节 × 命中/缺失/字数），缺节打监管违规 flag（E1）。
`【v2】` ① 年报/半年报双 schema，各自带文号与施行日；② schema 是法规原文的**可追溯派生**（原文 sha → 章节清单），禁止手敲 YAML；③ 2025-07-01 起适用新版，章节数与顺序随版本变化，**"10 节"不得硬编码**；④ 缺失三态化；⑤ 复用 recognition 已验证的序号连续性（cn/ar）与"一级标题识别 ≠ 一级标题分类"不变量作为判定语义参考，不复制实现；⑥ 非结构标题（如"小计"）由法定章节集排除，不得靠正则猜层级；⑦ E1 在法规原文采集并登记 sha 前不得运行。

**R'2 句子级最小单元**：`【v1】` 句子级最小分析单元；任何文本特征必须同时输出 cohort（申万行业 × 年份）内 z-score 与原始值。
`【v2】` ① cohort 用 **point-in-time 申万历史分类**，禁止当前成分回填历史；② 句子边界规则与分词器版本进 hash 锚；③ 每个特征可回指原文 span（M2）；④ 数值特征必须携带 `(concept, period, scope, unit)`，缺一即 fail。

**R'3 情感/语气双轨**：`【v1】` 情感/语气用 LM-2011 中文金融词典 + 自建年报语料 TF-IDF 衍生词典双轨；禁用通用 Hownet/NTUSD 作为主信号。
`【v2】` ① 词典原文 sha + 衍生脚本 commit 纳入 hash 锚；② 衍生词典必须**时序外**构造，不得用全期语料造 t 期特征；③ 词典版本变更必须重跑 E3/E4。

**R'4 表格对账**：`【v1】` 表格 → DataFrame → 报表项目 canonical 化 → 与东方财富/同花顺量化 DB 逐项对账，误差 ≤0.5% 或 ≤1 元；对账失败进 evidence 表，不静默丢弃（E2）。
`【v2】` ① XBRL 实例文档为主裁判、量化 DB 为交叉验证；② 三表勾稽作为无需外部 DB 的自校验先跑（资产=负债+权益；货币资金期末=现金流量表期末现金；未分配利润勾稽）；③ 失败按 §2.3 类型归类，致命类 0 容忍；④ 任何数值 frame 无 verbatim span 即 fail（禁止 LLM 造数）；⑤ 复用 01 已有 evidence 表机制，**不新建表**。

**R'5 forward-looking 双通道**：`【v1】` forward-looking 语句双通道抽取（规则初筛 + LLM 复核），单独建子语料与子特征矩阵。
`【v2】` ① **LLM 只做复核，不产出任何数值/事实**；② 若启用，模型权重 sha + `temperature=0` + prompt sha + 解码参数成为 hash 锚第五元（参考生态实测 temperature=0.1 自一致率仅 50%）；③ 不可锚定时降级为纯规则通道并显式标注 `resolution_state`，不得静默使用不可复现结果。

**R'6 四元 hash 锚**：`【v1】` 特征矩阵带四元 hash 锚（输入 MD sha set + 词典版本 + 分词器版本 + 管线 commit）；DVC 版本化；同输入同版本 byte-identical 重跑可证（E4）。
`【v2】` ① 新增第五元（归一化函数 / LLM 版本 / 判定程序 commit，按实际启用项）；② byte-identical 是**必要非充分**条件，须同时通过双路径收敛；③ 归一化函数与判定函数版本化并公开；④ 每个 frame 的 provenance 复用 `frame-v2.md` 既有字段语义（`source_hash` / `start_offset` / `end_offset` / `semantic_path` / `resolution_state` 四态 `UNAMBIGUOUS|CONFLICTED|AMBIGUOUS|UNRESOLVED`），**不自造枚举**。

**R'7（二期）缺失机制**：`【v1】` 缺失机制显式建模：1,688 unobtainable 进样本描述统计；用特征做回归时必须报告 Heckman 两步或等价校正（E5）。
`【v2】` ① 三态缺失分别建模，NOT_APPLICABLE 不参与选择偏差；② `EXTRACTION_FAILURE` 必须单列，不得伪装成"公司未披露"。

**R'8（二期）信号有效性**：`【v1】` 任何特征入主矩阵前必须证明与未来业绩（下期 ROE/营收增长率方向）相关 ≥60% 准确率（E3）。
`【v2】` ① 时序外评估；② 行业×年份固定效应；③ 特征不得使用 t 时刻未知信息；④ 评估脚本 commit 纳入 hash 锚。

**R'9（二期）监管印证**：`【v1】` 模型判"高风险/前瞻模糊"样本下一年被问询函覆盖比例显著高于基线（卡方 p<0.05）（E6）。
`【v2】` ① 问询函披露日期必须晚于特征计算时点（防倒挂）；② 基线构造方式随报告落盘，防止挑基线调 p 值。

---

## 四、取数边界裁定（v2 新增，具规范效力）

- **合法输入**：PG 交付表 `annual_semi.reconciled_report` + RustFS GET（winner_md_path / 桶键），以及 §2.3 列出的外部锚数据（法规原文、XBRL 实例文档、量化 DB 快照、申万历史分类、问询函、下期业绩、词典原文）。
- **未授权输入**：`source/html/sina/*`、`source/html/cfi/*`、`/source/.trash_20261109/ashare-bulletin/*`、`sina_bulletin.db`；禁止直连 `/backup`。
  - 依据：这些资产属于已废弃的 `ashare-bulletin`，不在交付表契约内；参考生态 `ashare-project/README.md`「实然不证应然」、`02-retention-classification.md`（ARCHIVE ONLY、不入 live）、`08-database-drop.md`（Human Gate 批准的 DROP）。
  - "字节还在"是实然观察，不等于"本 repo 可采"的应然授权。
  - **从 trash 恢复到 RustFS 属于对退役资产的写操作，禁止。**
  - 若需纳入，必须 Human Gate 批准并变更本节与 R'0；在此之前，任何 unit 不得读取上述路径。
- **连带作废**：02/03 中"从源 HTML 重建结构""恢复 ninefzt 源 HTML""Phase 1 结构丢失诊断实验"等条款不具规范效力（见 §七）。
- **不修改上游** `nooshare-annual-semi`；两个参考仓库 `ashare-bulletin-recognition` / `ashare-project` 仅只读参考，不进运行时。

---

## 五、停止规则（v2 新增）

1. **唯一门禁**：任一 unit 完成后先跑其绑定 E 的判定程序；不过不许合入（AGENTS.md 失控防御第 3 条）。不设"带着已知缺陷往上跑"的中间态。
2. **抽样停止规则**：按（法规版本 × 板块 × point-in-time 行业 × 难度层）分层，用**判别对**（同一 code/year/period、只差一个变量）持续抽，直到连续 k 份不产生新的失败类型即停，输出带置信界的覆盖结论。
3. **全量运行是生产行为，不是验证行为**；不设"全量放行"阶段，全量只证明"没崩"。
4. 前提未裁定时（§〇 未决 1-3），相关 E 判定程序**不得运行**，实验结果不具规格效力。

---

## 六、消费者与维护规则

见 `deliverables/05-consumer-contract.md`。核心事实：一期特征矩阵当前**无运行时消费者**（唯一消费者是二期的"未来 repo"）；在消费者缺位期间，E1-E6 是唯一能替消费者判定对错的机制，这正是 §2 不得被替换为检索类指标的原因。

---

## 七、权威收敛（v2 新增）

| 文档 | v2 状态 | 说明 |
|---|---|---|
| `deliverables/01-requirement.md` | **唯一需求权威（本文件）** | AGENTS.md 铁律 1 |
| `deliverables/02-framing-deep-requirements.md` | 执行参考，**非需求权威** | R''0-R''9 编号与其 E1-E6 标签作废；其诊断与工具清单可参考，验收指标不得引用 |
| `deliverables/03-framing-execution-plan.md` | 历史执行草案，**非需求权威** | R'''0-R'''7 编号、9 阶段关键路径、Phase 1、源 HTML/trash 恢复条款作废 |
| `deliverables/04-deep-rewrite-proposal.md` | **已合入归档** | 本版的变更依据；不再作为独立规格引用 |
| `deliverables/05-consumer-contract.md` | 契约（scoped） | 消费者与维护规则，不定义需求 |

- 禁止再产生新的 Requirement 代际（R''''）；需求变更一律改本文件并走抬头变更流程。
- 禁止 Agent 自行修改本文件、恢复 trash、扩大取数边界、把审计事实当作需求授权（参考生态："Agent 不能 invent project authority"）。

---

**对抗失控的根因机制**：spec-driven + 外部锚 gate。每个 R 绑一个外部客观标准，"做出来了"不算交付，"对得上外部锚"才算数；锚本身带身份与版本，判定程序本身可复现。
