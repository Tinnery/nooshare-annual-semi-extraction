# 一级标题 Pattern 积累法：深度重写提案（01 v2 的 U-H1 单元，不是第四代需求）

> Date: 2026-11-13 · **v2（已按 Human Gate 裁决 `①A ②A ③默认 ④A` 更新）**
> **Status: 提案（Authority: 无）— 用户裁定「暂不合入 01」，保持执行参考地位，不得作为规格引用**
> 唯一需求权威仍为 `deliverables/01-requirement.md`（v2）；本文件不修改 01、不新增 R 代际、不新增 E 编号、不新增依赖 / Phase / 表。
> 提出缘由：用户 2026-11-13「我需要这个任务的更深版本，而不是更大版本」+「一级标题用积累法」。
> 参考（只读）：`deliverables/02`（执行参考，其 R''/E 语义已作废）、`04`（已合入归档）、`05`（消费者契约）、`07`（裁决决策单）、`AGENTS.md`。
> **v2 变更依据**：上游 `C:\dev\nooshare-annual-semi` 交叉知识核对（见 `07` §〇，15 条资产）。③ 裁定「默认 = 继承上游已冻结参数」，故 U-H1.0 / U-H1.2 / U-H1.3 / U-H1.4 / U-H1.7 相应改写；② 裁定「不纳入 + 复用上游能力」，④ 裁定「暂不合入 01」。

---

## 〇、现状诊断：为什么上一轮是「更大」而不是「更深」

> **v2 状态注记**：下表是 2026-11-13 裁决前的**历史诊断快照**。第 1 条已由裁决 ①A 解决（`pytest -q` 现为 35 passed）；第 2 条的结论**仍作废不复用**；第 3–6 条描述的代码缺陷**依然存在**，是 U-H1 落地时必须处理的对象，但不得让旧路径进入主链路。

| # | 实证 | 规格后果 |
|---|------|---------|
| 1 | `python -m pytest -q` = **14 failed / 20 passed**。`test_spec.py` 仍断言 `applicability_rule_status == "UNRESOLVED"`，`REGULATORY_VERSIONS_SHA256` 仍登记旧值 `9a47…`，实际文件为 `0fba0f…` | 上轮把 `regulatory_versions.json` 改为 `RESOLVED` / `by_period_end` 后，未同步 01 §〇 sha 登记、`test_spec.py`、`anchors.json` 的 `blocked_until`、05 契约 gate 状态。按 05 C2.4，E1 判定程序应为 `BLOCKED_ON_GATE` |
| 2 | `batch_e1_validation.py` 对 100 份 + 36,970 份跑了 E1 合规判定 | 在 gate 未同步状态下运行，结论**不具规格效力**；且违反 01 §五.3「全量运行是生产行为，不是验证行为」 |
| 3 | `chapter_extractor.py:50` 用 `re.sub` 去页码 + `strip()` 后拼成 `"第X节 标题"`，丢弃 `start_offset` / `end_offset` / `verbatim_span` / `source_hash` | 违反 M2（可反驳性）：清洗后的字符串无法一键回到原文。按 M2「做不到即判 fail，不进统计分母」，当前所有合规率数字在规格上不进分母 |
| 4 | `chapter_extractor.py:21` 与 `scripts/extract_chapter_pattern.py:26` 各有一份**手敲** `CHAPTER_KEYWORDS` | 违反 R'1②「schema 是法规原文的可追溯派生，禁止手敲」与 R'1⑥「不得靠正则猜层级」；两处关键词表还不一致 |
| 5 | `e1_judge.py` 用 `_matches()` / `_matches_split()` 的模糊包含、字符集合重叠 >0.7、关键词覆盖 ≥50% 来"凑"命中 | 这些阈值无外部身份，不可反驳、不可复现；是"让输出看起来对"，不是"证明对" |
| 6 | 用户原方案「让 AGENT 判断是否符合正确的标题」 | AGENT 判断无 verbatim span（违 M2）、不可锚定（04 §2-H 实测 temperature=0.1 自一致率仅 50%，违 E4）、无外部身份（违 M1）。04 §2-F 已把「人工标注当 oracle」判为循环论证并排除 Cohen's κ；AGENT 判断是同类错误的更弱版本 |

**根因**：上一轮在**没有裁判的情况下扩大了样本量**。更深的版本不是多跑数据，是先确定「什么算对」，再决定跑多少。

---

## 一、顶尖专家会采取、而当前方案没有的做法

### A. 先区分「全量提取」与「全量判定」——你的第一步其实可以保留
01 §五.3 禁的是**用全量当验证**，不是禁全量产出。用户方案里「第一个版本全量提取一级标题」是**候选生成**（不声称正确），合法且必要；被禁的是「全量跑 E1 得出合规率」。
重构：`candidate pool`（全量、无裁判、可分层计数） ≠ `replay set`（全量、只读、永不移出、用于零回归验证）。

### B. 用「同一 MD 内的目录页 / 正文双现」替代「参考 HTML」——不越界拿到第二独立信源
用户想用 HTML 提供交叉验证。但 01 §四 / `anchors.json.forbidden_sources` 明确 `source/html/sina/*`、`source/html/cfi/*` **未授权**，01 v2 §七已把 02 的「回到源 HTML」条款作废（04 §1「实然不证应然」）。
专家做法：年报 MD 里天然存在**两个独立观察**——目录页的标题行（带页码/点线）与正文的标题行（独立排版）。把这两条路径分别提取、规范化到同一 canonical 元组，正是 E4 要求的**双路径收敛**。既满足外部交叉验证，又无需 Human Gate 扩边界。若确需源 HTML，走 01 §四变更流程。

### C. 频次是最弱的学习信号，会被「模板厂分布」绑架
A 股数千家公司共用同一批财经印刷 / IR 服务商的 Word 模板。**最高频组合是模板厂的产物，不是法规的正确结构**；且高频 = 最易、最无信息量，真正的失败类型藏在长尾。
01 §五.2 已冻结更强规则：按（法规版本 × 板块 × point-in-time 行业 × 难度层）分层，用**判别对**（同 code/year/period、只差一个变量）驱动，连续 k 份不产生新失败类型即停，输出带置信界的覆盖结论。频次退化为**分层内的候选排序**，不作正确性裁判。

### D. pattern 必须按 `(reg_version, period, condition_state)` 分层计数，不能全局混池
`legal_chapters.json` 实证：〔2016〕31号 12 节、〔2021〕15号 10 节、〔2025〕3号 8 节；优先股 / 债券为 `conditional`。把 2021-2024 全量混在一起数频次，会把**版本差异**与**条件不适用**误归因为「提取失败 / 未披露」——正是 E1 `failure_taxonomy` 的前三项（版本选错、准则串用、NOT_APPLICABLE 误报为缺失）。

### E. 「命中即脱离第二轮」是贪心集合覆盖，有三个未定义歧义
- **冲突**：一份 MD 命中两条 pattern 时如何裁决？需 specificity 排序 + 最长匹配 + 确定性 tie-break，冲突落 evidence 表，不静默取第一条。
- **顺序偏差**：先入的宽 pattern 会吃掉本该由精确 pattern 解释的 MD，且不可撤回。
- **零回归**：移出计算后无法发现「加了新 pattern 让旧命中的判定变了」。
专家做法：命中集合从 **candidate pool** 移出（允许），但**保留在 replay set**（永不移出）；每轮对 replay set 只读回放，验证旧命中结论逐字节不变（M3 / E4）。并报告**残差集**（始终未被任何 pattern 命中的 MD）及其分层分布，而非只报覆盖率。

### F. 一级标题「识别 ≠ 分类」：必须分两本 pattern
01 R'1⑤ 已引用 recognition 验证过的不变量。混在一起会让「标题误升格」（E1 失败分类末项，如公司名称 / `目 录` / 表头 `小计`）伪装成缺失。
- **L1 边界检测 pattern**：序号连续性（cn/ar 双主体系）、目录页/正文双现、页首位置——只判「这行是不是一级标题」。
- **L2 语义归一 pattern**：映射到 `legal_chapters.json` 的哪一节——只判「对应法规哪一条」，且必须可追溯到法规原文 verbatim。

### G. 「记录命中 md 的个数」是必要非充分
个数无法证明可复现。需同时记录：命中集合的 **sha256**、pattern 库冻结版本、归一化函数版本、判定程序 commit（M3）、每条 pattern 的边际新增覆盖、near-miss 反例。按 05 C3，pattern 库属判定程序，变更走 MINOR / MAJOR 并重跑全部 E（C4）。

### H. 举证责任分级：判「公司违规」比判「提取正确」严得多
三态（01 E1）不是标签，是举证责任：
- `NOT_APPLICABLE`：由 `reg_version` + `condition` 判定，零举证；
- `EXTRACTION_FAILURE`：由双路径分歧 / span 缺失判定，工程 fail；
- `NOT_DISCLOSED`：**必须人工复核原文 MD/PDF 确认该章节确实不存在**，且 L1 检测已通过。任何 pattern 未命中都不得直接落此态。

---

## 二、未经加工的原始数据 / 具体工具 / 专业方法

### 2.1 原始数据（**授权裁定是前三版完全缺失的一列**）

| 数据 | 外部身份 | 授权 | 用途 |
|---|---|---|---|
| `annual_semi.reconciled_report` 交付表行 | slot → `winner_md_path` → 桶键 → sha256 | ✅ 唯一合法入口 | 论域、sha 锚 |
| RustFS `published/*.md` **原始字节** | 上游 `proof.json`（gate_fail=false） | ✅ | 唯一未加工语料；必须保留原字节，清洗结果只作派生列 |
| 5 份法规原文 PDF **原始字节** + sha256 | 〔2016〕31 /〔2021〕15 /〔2025〕3 /〔2021〕16 /〔2025〕4 | ✅ 外部锚 | 「正确标题组合」的**唯一**定义来源 |
| `chapter_structures.json` | 从上述 PDF 提取的章/节/条 preview | ✅ 派生 | 法规侧 verbatim 比对 |
| `legal_chapters.json` | `reg_version` → sections（含 `required` / `condition`） | ✅ 派生 | L2 归一目标、三态判定 |
| 上游 `proof.json` + 1,688 unobtainable 清单 | 只读证据 | ✅ | E5 / 残差集分层 |
| recognition 资产：`report_heading`(907,705)、`heading_verdict`(19,183 裁定 / 17 类)、cn/ar 序号连续性契约 | `C:\dev\ashare-bulletin-recognition` | ⚠️ 只读参考，不进运行时 | 复用判定语义，不复制实现（铁律 4） |
| `source/html/sina/*`、`source/html/cfi/*`、`.trash_20261109/*`、`sina_bulletin.db` | 已退役 `ashare-bulletin` | ❌ **未授权** | 需 Human Gate 变更 01 R'0 后才可采；在此之前任何 unit 不得读取 |
| 年报源 PDF / PDF Outline 书签 | 巨潮 as-filed | ❌ 未列入 §四合法输入 | 若需作为交叉裁判，须走变更流程（当前用 §一.B 的 MD 内双路径替代） |

> **注意「未加工」的边界**：当前 `chapter_extractor.py` 输出的 `["第一节 重要提示", ...]` 已是**加工产物**。真正的原始证据是 MD 字节 + `(source_hash, start_offset, end_offset, verbatim_span)`。

### 2.2 工具（零新增依赖，05 C6 / 04 §3.2）

| 工具 | 用途 | 约束 |
|---|---|---|
| `hashlib` / `re`（stdlib） | 原字节 sha、候选生成 | 正则**只作候选生成**，不作层级判定（R'1⑥） |
| `difflib`（stdlib） | 标题变体近邻聚类、编辑距离 | 不引入 `rapidfuzz` / 向量相似度 |
| `sqlite3`（stdlib） | 组合频次、命中集合、快照版本化 | **不新建 PG 表**（05 C6）；计数字段带分层键 |
| `pytest` + 属性测试 | 不变量：命中集合单调性、删一行目录页不得改变其他 slot 的判定、回放零回归 | 复用既有测试栈 |
| `git` + sha256 | pattern 库冻结、判定程序 commit 入五元锚 | M3 |
| `pypdf` / `pdfplumber`（若启用） | **仅**从已授权的 5 份法规 PDF 抽 verbatim 标题 | 不用于年报 PDF |
| AGENT / LLM | **仅**候选生成 + 分歧仲裁 | 若启用：模型权重 sha + `temperature=0` + prompt sha 入第五元锚；只做复核、不产出事实（R'5） |
| **明确不进主链路** | Qdrant / spacy / sentence-transformers / LayoutLM / ollama 做裁判 | 04 §3.2 已排除；破坏 E4 且与 RAG 产品无关 |

### 2.3 专业方法

法规版本 point-in-time 分层 · 目录页/正文**双路径收敛**（分歧落 evidence 表，不静默丢弃）· cn/ar 序号连续性 · **判别对 / 最小对立对**（只差一个变量隔离失败原因）· 错误类型饱和抽样（sequential stopping，01 §五.2）· **覆盖率饱和曲线**（每加一条 pattern 的边际新增覆盖，连续 k 条 < ε 即停）· 残差集分层报告 + 置信界 · 回放零回归 · 三态缺失 + 举证责任分级 · verbatim span 回指 · 冻结评审 + near-miss 反例库 · 判定程序 / 归一化函数版本化 · 属性测试不变量。

---

## 三、外部客观标准（**不新造 E**，全部复用已注册的锚）

| 锚 / 元规则 | 身份 | 用它证明什么 |
|---|---|---|
| **E1@anchors:v2:1** | 第2号 / 第3号各版文号 + 施行日 + **原文 sha256** → `legal_chapters.json` | 「正确的一级标题组合」的**唯一**定义。pattern 命中集必须收敛到该 `reg_version` 的法定节集；不得由频次、关键词表或 AGENT 判断定义 |
| **M2 可反驳性** | `source_hash` + `start_offset` + `end_offset` + verbatim span | 每条 pattern、每个命中可一键回原文；做不到即 fail，**不进统计分母** |
| **E4 双路径收敛** | 目录页路径 vs 正文路径 → 同一 canonical 元组；`diff=0` 是必要非充分 | 「提取正确」而非「看起来对」；稳定地错误的管线同样 diff=0 |
| **M3 判定程序版本化** | pattern 库版本 + 归一化函数版本 + 判定程序 commit 入五元 hash 锚 | 换 pattern 必须重跑全部 E；结果可复现、可回滚 |
| **E1 三态 + 失败分类学** | `NOT_APPLICABLE` / `NOT_DISCLOSED` / `EXTRACTION_FAILURE` | 「没命中」的性质；判 NOT_DISCLOSED 举证责任最高 |
| **01 §五 停止规则**（继承上游 S-3） | `monotonic_check=pass` + 每轮差集 receipt + `DIVERGENT_THRESHOLD=0.3` + `year×period×source` 分层抽样 ~5% | 何时停止积累；全量只证明「没崩」；不新造 k / ε |
| **05 C2/C3/C4** | gate 状态、schema semver、变更→重跑矩阵 | 前提未裁决时停机；pattern 变更走 MINOR/MAJOR |

**明确不作裁判**（01 §2.3 / `anchors.json.excluded_acceptance_metrics`）：Recall@10、cell-level 人工准确率、Cohen's κ、AGENT 主观判断、命中频次百分比、合规率百分比。

---

## 四、重写后的需求：U-H1（R'1 下的判定程序单元）

> 编号沿用 R'0-R'9 / E1-E6 / M1-M3，**不新增 Requirement 代际**（01 §七）。每条绑定既有锚 + 停止条件 + 可机器校验产物。

**U-H1.0 前置门禁（绑定 05 C2.4 / M1）—— ✅ 已解除（2026-11-13，裁决 ①A）**
E1 判定程序与 U-H1 的运行前提是 gate 状态一致：`regulatory_versions.json`、`anchors.json.blocked_until`、01 §〇 sha 登记、`test_spec.py` 断言五处同步。人类已追认 `by_period_end`，上述五处由 `07` §① 执行清单统一补齐；`python -m pytest -q` = **35 passed**（含新增的串报告防护测试），U-H1 状态 = `GATE_OPEN`。此前 `BLOCKED_ON_GATE` 期间产出的 100 份 / 36,970 份合规结论**仍不具规格效力**，不得复用。

**U-H1.1 原始证据保真（绑定 M2）**
对每份 MD 保留原字节 sha256；每个候选标题记录 `(source_hash, start_offset, end_offset, verbatim_span, capture_path ∈ {toc, body})`。清洗 / 归一化结果只作派生列，**不得覆盖 verbatim**。缺任一字段即 fail，不进分母。
*验收*：随机抽 1% 候选，`md_bytes[start:end].decode() == verbatim_span` 命中率 100%。

**U-H1.2 双路径收敛：复用上游，不自建（绑定 E4 / 01 §四 / 铁律 4）—— 裁决 ②A**
交叉核对发现上游 `annual_semi/completeness/dual_channel.py` **已实现 HTML/PDF 双通道 + `jaccard_distance` + `DIVERGENT_THRESHOLD=0.3`（D-3 冻结）**，`identify/_funcs/heading_verify.py` 已产出 canonical 章节签名，`semantic/_funcs/report_structure.py` 已有 `is_toc()/is_heading()/heading_level()`。故：
- **不纳入**源 HTML / 年报 PDF 到下游取数契约（01 §四维持不变）；交付表 11 列中无 PDF/HTML 路径字段，且本地 `artifacts/` 无双通道产物落盘。
- **不自建** MD 内目录/正文双路径（v1 此条属重复实现，作废）；改为**只读复用上游能力与结论**：`reference/report_patterns.json` 的 15 类 canonical 变体映射、`extract_heading_signature`、`jaccard_distance`、`candidate_count`/`multi_source` 代理。
- 两路径分歧落 evidence 表，不静默取其一；上游 02 已裁决「`patterns` 只是 Top-5 种子，**无需补 357 条**」。
*验收*：U-H1 不得出现任何与上游 #1/#3/#4/#6 功能重叠的新实现；收敛率按 `year × period × source` 分层报告；分歧样本可枚举。

**U-H1.3 分层候选池，频次只作排序（绑定 E1 / 01 §五.2）—— 裁决 ③「默认 = 继承上游」**
不新造分层维度与难度层，直接继承上游 `01-requirements.md` 的冻结参数：
- 分层键：**`year × period × source`**（上游 F-013 / §7.4 / §5 标准 6），每层抽样 ~5%（最少 1 个），抽样覆盖率 100%、人工 pass ≥95%；叠加 `(reg_version, condition_state)` 作版本与条件隔离，禁止跨版本混池。
- 难度代理（可观测，不主观打分）：`candidate_count`（`multi_source` ≥2 / `single_source` =1）、`winner_source`、`selection_rule`（`backup_l0/l1/l2`）、`unobtainable_reason`。
- 组合标识：复用上游 **F-012 结构指纹**（章节标题序列 SHA-256），不另造 id。
- 残差基线：`deliverables/completeness_2021_2024.json`（expected 37,406 / delivered 36,969 / unobtainable 437，全 `source_403_blocked`；`by_year_period` 八层）。
- 判别对：同一 `(code, year, period)` 且 `candidate_count >= 2` 的多源槽位即天然判别对（只差 `source`），`single_source` 单列。此为 01 §五.2「同一 code/year/period、只差一个变量」的正确解释（一个 slot 只有一份 MD，字面无法构造）；**不改写 01 原文**。
记录命中集合 sha256 与个数；频次仅作**分层内**候选排序，不作正确性裁判。
*验收*：任意两个 `reg_version` 的计数不可合并；conditional 节单列 `condition_state`；分层键与上游 F-013 一致。

**U-H1.4 两本 pattern 分离（绑定 R'1⑤ / R'1⑥ / 铁律 4）—— 裁决 ④A：先做资产映射**
`L1_patterns`（边界检测）与 `L2_patterns`（语义归一 → `legal_chapters.json` 节号，须可追溯法规原文 verbatim）分别积累、分别冻结。但**不得从零实现**：L1 复用上游 `is_toc()` / `is_heading()` / `heading_level()` / `clean_heading_prefix()` 与 `patterns.py` 的标题规范化（全角、异体零、中文数字年 cn→ar）；L2 复用上游 `canonical` 15 类变体映射 + `extract_heading_signature`（最长变体优先）。
**合入 01 前的前置动作**：产出一份「U-H1 每条能力 → 上游既有实现」的资产映射表，标出真正的增量部分；凡上游已有者一律复用，禁止复制实现（这是 ④ 裁定暂缓合入的直接原因）。
*验收*：公司名称 / `目 录` / `小计` 等噪声由 L1 排除且不产生 missing；下游 `chapter_extractor.py` 的手敲 `CHAPTER_KEYWORDS` 不得进入 U-H1 主链路。

**U-H1.5 裁判来源：AGENT 只生成候选与仲裁（绑定 M1/M2/E4 + 04 §2-F）**
「组合是否正确」的裁判是 ① 法规原文 verbatim（已登记 sha 的 5 份 PDF）与 ② MD verbatim span + 双路径收敛。AGENT 只做候选生成与分歧仲裁，**不得作为正确性 oracle**；若启用，其权重 sha / `temperature=0` / prompt sha 入第五元锚，且只复核不产出事实。
*验收*：每个被接受的 pattern 附 `legal_basis`（原文 PDF sha + 条款定位）与 ≥1 个 near-miss 反例；无 `legal_basis` 的 pattern 不得入冻结库。

**U-H1.6 积累循环：移出候选池，不移出回放集（绑定 M3 / E4）**
每轮：取分层内最高频候选 → 双路径验证 → `legal_basis` 比对 → 入冻结库并记录边际新增覆盖 → 命中集合从 candidate pool 移出。冲突按 specificity 排序 + 确定性 tie-break，冲突落 evidence 表。**每轮对全量 replay set 只读回放**，验证所有旧命中结论逐字节不变；出现回归即本轮作废。
*验收*：回放 diff = 0；命中集合单调不减；残差集按分层报告。

**U-H1.7 停止规则（绑定 01 §五 / 上游 S-3）—— 裁决 ③「默认 = 继承上游」，不新造 k / ε**
不设自拟 `k=30`、`ε=0.1%`、Chao1 等参数，直接继承上游已冻结的判定：
- **主停止判据 = 上游 S-3 单调收敛**：缺失集 `M0 ⊇ M1 ⊇ … ⊇ Mn`，每轮差集有逐条 receipt，`monotonic_check = pass`；终态 `Mn = ∅` 或全 `UNOBTAINABLE`。`proof-2018-final.json` 实测 M0=2030 → M1=0 → M2=0，`gate_fail=false`。
- **分歧阈值 = `DIVERGENT_THRESHOLD = 0.3`**（Jaccard 距离，上游 D-3 冻结）；分歧不自选胜者，回入 `M_n` 待裁决。
- **不设边际覆盖 ε**：上游 `02-technical-solution.md` 已裁决「`patterns` 只是 Top-5 种子，`extract_heading_signature` 只用完整 15 类 canonical 变体映射，**无需补 357 条**」，故"积累到饱和"的停止条件由 S-3 承担，不另设阈值。
- **分层抽样验收**：`year × period × source` 每层 ~5%、覆盖率 100%、人工 pass ≥95%。
**全量回放是生产行为，不是验证行为**；不得输出「全量合规率」作为验收结论。
*验收*：输出冻结版 pattern 库 + `monotonic_check` 证据链 + 残差集清单（对齐 2021–2024 基线）+ 三态分层矩阵，全部带 sha 与 commit。

**U-H1.8 三态与举证责任（绑定 E1）**
pattern 未命中 → 先判 `EXTRACTION_FAILURE`（双路径分歧 / span 缺失）或 `NOT_APPLICABLE`（`reg_version` + `condition`）；仅当 L1 通过且人工复核原文确认章节不存在时，方可判 `NOT_DISCLOSED` 并打监管 flag。三类不得混计。
*验收*：每个 `NOT_DISCLOSED` 附复核证据路径；缺证据即降级为 `EXTRACTION_FAILURE`。

**U-H1.9 冻结与变更（绑定 M3 / 05 C3-C4）**
pattern 库、归一化函数、判定程序一并版本化并纳入五元 hash 锚；任何变更走 MINOR/MAJOR 登记并**重跑全部 E**。禁止在消费者缺位期间为「将来可能被用」扩列、扩索引、扩粒度（05 C5.3）。
*验收*：`tests/test_spec.py` 全绿；冻结库 sha 与 01 §〇 登记一致。

---

## 五、与用户原需求的逐条 diff

| 用户原句 | 重写后 | 变化性质 |
|---|---|---|
| 「第一个版本全量提取一级标题」 | U-H1.1/1.2：全量**提取**合法，但须带 verbatim span + 双路径 | 保留 + 补可反驳性 |
| 「同时参考 HTML 和 MD」 | U-H1.2：**不纳入**源 HTML/PDF（01 §四维持）；改为只读复用上游已实现的 HTML/PDF 双通道 + canonical 签名，不自建双路径 | **边界裁定 + 复用**（裁决 ②A / 铁律 4） |
| 「选取出现次数最多的组合」 | U-H1.3：频次降级为分层内排序，不作裁判 | 换裁判 |
| 「让 AGENT 判断是否符合正确标题」 | U-H1.5：AGENT 只生成候选 / 仲裁；裁判 = 法规原文 verbatim + 双路径收敛 | **换 oracle**（去循环论证） |
| 「积累到 pattern 库，记录命中 md 个数」 | U-H1.4/1.6/1.9：两本 pattern + 命中集合 sha + 边际覆盖 + 冻结版本 + commit 入锚 | 补可复现性 |
| 「再分析第二个命中多的组合」 | U-H1.6/1.7：判别对优先 + 饱和度停止，非纯频次轮转 | 补停止判据 |
| 「被命中的集合脱离第二轮计算」 | U-H1.6：移出 candidate pool，**保留在 replay set** 做零回归 | 消解贪心偏差 |
| （未提） | U-H1.0：先解除 gate 不一致 —— **已解除，35 passed** | **前置阻断 → 已通过**（裁决 ①A） |

---

## 六、Human Gate 裁决结果（2026-11-13，`①A ②A ③默认 ④A`）

| 项 | 裁决 | 执行结果 |
|---|---|---|
| ① gate 不一致修复 | **A** 追认 `by_period_end`，统一同步 | ✅ 已执行：01 §〇 两个 sha 登记 + 未决清单 + 变更登记 v2.1；`anchors.json` E1 `blocked_until=null`；`test_spec.py` 改断言；`test_e1_judge.py` 补 `report_year`/改断言/改用合法 `slot_key`；`e1_judge.py` 与 `batch_e1_validation.py` 复用上游 `slot_key`/`parse_slot_key`。**`pytest -q` = 35 passed** |
| ② 源 HTML / 年报 PDF | **A** 不纳入，复用上游能力 | ✅ 01 §四 / `anchors.json.forbidden_sources` **未改动**；U-H1.2 改写为只读复用上游双通道与 canonical 签名，不自建路径 |
| ③ k / ε / 难度层 / 判别对 | **默认 = 继承上游** | ✅ U-H1.3 / U-H1.7 改写：分层 `year×period×source` ~5%、停止用 S-3 `monotonic_check`、分歧用 0.3、组合标识用 F-012 结构指纹；**不新造参数** |
| ④ 本提案合入 01 | **A** 暂不合入 | ✅ 01 正文 R'0-R'9 / E1-E6 未改；本文件保持 `Authority: 无`；合入前须先产出「U-H1 → 上游资产映射表」 |

**仍未解决、需后续 Human 动作**（本次裁决未覆盖）：
1. 上游双通道产物 `dual_channel_report.json` / `divergent.jsonl` 本地 `artifacts/` 无落盘；需确认是否在 pro 主机 / RustFS，否则 E4 双路径只能以 `candidate_count`/`multi_source` 代理。
2. 「U-H1 → 上游资产映射表」尚未产出，是 ④ 合入 01 的前置条件。
3. `chapter_extractor.py` 的手敲 `CHAPTER_KEYWORDS` 与清洗销毁 verbatim span 的问题仍未修复（M2）；U-H1 落地时须一并处理，但不得让旧路径进主链路。

---

## 七、生效条件与禁止项

- 本文件**不修改** 01 正文的 R'0-R'9 / E1-E6 语义；① 对 01 的改动仅限 §〇 变更登记与 sha 登记（已获 Human Gate 授权）。AGENTS.md、README、02/03/04/05 未改；不新增依赖 / Phase / 表。
- 禁止：以 AGENT 判断 / 频次 / 模糊匹配阈值作为正确性裁判；以全量合规率作为验收；读取未授权源；产生新的 R 代际或 E 编号；重复实现上游已有能力（铁律 4）。
- gate 已解除，但 **此前 `BLOCKED_ON_GATE` 期间的验证结论仍全部作废**。
- 下一步（按依赖顺序）：① 产出「U-H1 → 上游资产映射表」；② 设计 U-H1.1 的 evidence 字段（`source_hash` / `start_offset` / `end_offset` / `verbatim_span` / `capture_path`）；③ 确认双通道产物可得性。三项均为文档级、零依赖、可逆。

---

**END OF DOCUMENT**
