# R'0-R'9 深度重写提案（01 的 delta，不是第四代需求）

> Date: 2026-11-13
> **Status: 已合入归档 — 2026-11-13 用户「按照顺序落地需求」指令批准，内容已并入 `01-requirement.md` v2**
> **Authority: 无。唯一需求权威为 `deliverables/01-requirement.md`（v2）；本文件不得被独立引用为规格。**
> 落地工件：`annual_semi_extraction/spec/anchors.json`、`annual_semi_extraction/spec/regulatory_versions.json`、
> `deliverables/05-consumer-contract.md`、`tests/test_spec.py`；权威收敛见 01 v2 §七。
> 参考资料：`C:\dev\ashare-bulletin-recognition`、`C:\dev\ashare-project`（只读，不进运行时）

---

## 0. 为什么这一版是"更深"而不是"更大"

| 维度 | 02 / 03 的做法 | 本提案 |
|------|---------------|--------|
| 需求代际 | 新增 R''0-R''9、R'''0-R'''7（共 3 代并存） | 沿用 R'0-R'9，**编号不变，不新增代际** |
| 验收锚 | 重新定义同名 E1-E6（3 套语义） | 沿用 01 的 E1-E6 原义，**只深化判定程序** |
| 权威文档 | 02、03 各自声明 `Authority: 自身` | 收敛回 01 一份；02/03 降级为执行参考 |
| 数据边界 | 恢复 trash 300GB、直取 `source/html/*`、`sina_bulletin.db` | 不变（铁律 2），越界项走变更流程 |
| 依赖 / 阶段 | 新增 lxml/spacy/sbert/qdrant/networkx/ollama + 9 Phase | **零新增依赖、零新增 Phase、零新表** |
| 深化了什么 | — | 每个 E 的判定函数、每个 R 的可反驳条件、失败分类学、停止规则 |

净效果：需求对象数减少，判定力提高。

---

## 1. 前提问题重裁：最大的不确定性不是"源 HTML 还在不在"

用户原命题：「R''0-R''9 中最大的不确定性是源 HTML/PDF 是否还在」。审计证明"在"，于是 03 判定「R''1 前提完全成立」。这一步在参考生态里是明确禁止的推理：

- `ashare-project/README.md` 关键原则 2「**实然不证应然**」：代码存在 ≠ 应该存在；当前状态 ≠ 未来义务。
- `changes/ashare-sources-retirement/02-retention-classification.md:324`：「当前代码用了这些表名 ≠ 必须保留 ashare-sources 的数据」；同文件 §分类把快照列为 `ARCHIVE ONLY`（"不入 live；释放与否 = Human 决定"）。
- `08-database-drop.md`：旧库由 **Human Gate 批准** `DROP DATABASE`，唯一保留物是 rollback archive（带 sha256）。退役是有授权的语义决定，不是意外丢失。

同时，01 R'0 与 AGENTS.md 铁律 2 把取数锁在 `annual_semi.reconciled_report` + RustFS GET。03 §2 列出的 `source/html/sina|cfi/*`、`.trash_20261109/ashare-bulletin/*`、`sina_bulletin.db` 全部来自**已被废弃的 `ashare-bulletin`**，不在交付表契约内；03 §4.3 计划"从 trash 恢复到 RustFS"更是对已退役资产的**写操作**。

因此「存在」已证，「可采」未证。真正最大的不确定性按影响排序是：

1. **验收锚的身份**：01（L17-24）、02（L176-242）对同名 E1-E6 给出完全不同语义；03 的门禁（L154-160、L400）用 02 的语义，却在 R'''3 写「绑定 E1-E6」并声称 01 为上游。**同一个标签对应两个判定函数，所有 gate 都是空绑定**——这是证明系统的错误，不是工作量不足。
2. **消费者不存在**：`f0-statistics.md:150-160` 的 Consumer Audit 显示 `report_frame`（18,231,500 行）、`report_frame_v2`、Qdrant collection 全部 **NONE FOUND**；`is_valuable = true` 为 0。`jq-decoded-artifact.md:517` 的事后结论是「It had no consumer and no maintenance rule」。01 把特征矩阵的唯一消费者放在"二期未来 repo"。**在消费者缺位时，E1-E6 是唯一能替消费者判定对错的机制**——02/03 把它们换成服务于一个本 repo 并不存在的 RAG 系统的 Recall@10，是双重退化。
3. **取数合法性**：不是"文件在不在"，是"规格是否授权"。这一项需要 Human 裁决，Agent 不能自行扩张（`agent-evidence-authority.md:48-68` Governor Gate）。

**结论**：`R''1 前提完全成立` 只在字节存在性上成立。Phase 1 诊断实验绑定在未裁定的取数边界与未锁定的锚上，**不应启动**。

---

## 2. 顶尖专家会采取的、02/03 没有的做法

| # | 做法 | 依据（可核查） | 为什么是"更深" |
|---|------|---------------|---------------|
| A | **先锁锚身份，再谈门禁**：给每个锚不可变 ID `E{n}@01:<doc_sha>:v1`，需求引用必须带身份，禁止跨文档裸标签复用 | 01 L17-24 vs 02 L176-242；03 L6/L16/L406-457 自相矛盾（声称"不增加需求条目"却新建 R'''0-R'''7） | 不修证明系统，再多 Phase 也只是更精确地跑错 |
| B | **实然 / 应然分层裁定**：审计结果落成 Reality 记录，能否作输入落成 Human Decision | `ashare-project/README.md:99-112`；`02-retention-classification.md:10` 明确"不批准删除、不进入 P2" | 把一次磁盘探测升级成一次治理裁决，不扩一行代码 |
| C | **复用已建成的结构资产，而不是从源 HTML 重建** | `frame-v2.md:40-91` 已规定 `source_hash`/`start_offset`/`end_offset`/`semantic_path`/`resolution_state` 四态枚举；`f0-statistics.md:134-147` 源保真 **8/8 PASS**（`part.text == md_text[start:end]` + sha）；`report_part.source_hash` 覆盖 100%；recognition `AGENTS.md:88` 冻结 `char_pos` 契约 | 02 L42「frame_text ≡ source[start:end] 从未被验证」与事实不符；03 做法 I「Provenance chain（你没想到的）」是**重复实现**，违反铁律 4。另外 02 的 `DEGRADED_FROM_MD` 不在既有四态枚举内，是未经变更的语义分叉 |
| D | **先固定消费者与维护规则，再固定产出格式** | `f0-statistics.md:150-160`；`jq-decoded-artifact.md:517-519`；`agent-evidence-authority.md:57-68` | 上一代失败的根因不是结构丢失，是 1823 万帧无人消费。更深的问题是"谁读、读什么、何时算过期"，不是"索引做几级" |
| E | **法规版本是函数，不是常量；年报与半年报分锚** | 年报＝《准则第2号》：〔2016〕31号 →〔2021〕15号 → **〔2025〕3号（2025-07-01 施行）**；半年报＝《准则第3号》：〔2021〕16号 → 2025 新版（同日施行并废止 16 号）。2025 修订**调整篇章布局、删除董事会/股东会章节、把"优先股相关情况"并入股份变动章节** | 03 的 `schema/2024.yaml`（L264-279）把「第八节 优先股相关情况」列为 required，且用一套 schema 覆盖 2018-2026、只锚 §2；半年报（period=2）的章节合规**根本没有锚**。01 R'1 的"当年版本"应实现为 `reg_version(period, disclosure_date) -> 文号 + 原文 sha256` |
| F | **用监管强制产物当 oracle，不用人工标注当 oracle** | 巨潮/深交所 XBRL 实例文档（报送时法定同时提交，四级标记，五张报表，as-filed）；01 E2 的东方财富/同花顺量化 DB；SEC Financial Statement Data Sets 是同范式先例 | Cohen's κ 只测两个标注员是否一致，不测是否正确；人工录入 50 张表是循环论证。03 L142 把 κ≥0.7 当门禁、L366 把人工 cell 录入当 E4，反而**丢弃了 01 里最强的外部锚**。人工只做分歧仲裁（adjudication），复用 `heading_verdict` 的 `ON CONFLICT DO NOTHING` + 人工晋升机制 |
| G | **失败分类学优先于百分比阈值；复用 SlotKey** | 铁律 4（优先复用上游 SlotKey）；`repo-logos/invariants.md:5-10` | 最贵的错误不是漏抽，是**错配**：期间（本期/上期）、口径（合并/母公司）、单位（万元/元）、主体（串报告）、跨页断行、LLM 补全数值。每个数值 frame 必须携带 `(concept, period, scope, unit, source_span)` 五元组；**无法给出原文 verbatim span 即判 fail**（禁止造数）。阈值按错误类型分别给，致命类 0 容忍 |
| H | **可判定等价取代 diff=0；LLM 复现性显式锚定** | recognition `AGENTS.md:70`：`LLM_TEMPERATURE` 由 0.1 改 0，因为「判节须可复现，实测 0.1 自一致率仅 50%」；03 §3.1 让 ollama 参与 proposition/表格摘要/引用语义确认 | byte-identical 只证明确定性：一条稳定错误的管线同样 diff=0。更深的标准是**双路径收敛**（MD 路径与结构路径规范化到同一 canonical 元组，分歧进 01 R'4 已有的 evidence 表）+ **归一化函数版本进 hash 锚**。且 01 的四元锚没有模型权重/temperature/prompt 维度，LLM 一进主链路，E4 就不可满足 |
| I | **三态缺失 + 错误类型饱和停止规则** | `docs/plans/S9-structure-verdict.md` 的序号连续性（cn/ar 双主体系、`contiguous_from_1`/`has_gap`/`front_matter_offset`）；01 E5 | 「空」必须分 `NOT_APPLICABLE`（当年法规不要求）/ `NOT_DISCLOSED`（法规要求但未披露→监管 flag）/ `EXTRACTION_FAILURE`（工程缺陷），否则 E1 的 missing 计数从根上混了。全量 72K 只能证明"没崩"；按 (法规版本×板块×行业×难度层) 做**判别对抽样**，连续 k 份不产生新失败类型即停，给带置信界的覆盖结论 |

---

## 3. 未经加工的原始数据 / 工具 / 专业方法

### 3.1 原始数据（"边界裁定"是前两版完全缺失的一列）

| 数据 | 外部身份 / 位置 | 边界裁定 | 用途 |
|------|----------------|---------|------|
| 交付表行 `annual_semi.reconciled_report` | slot → winner_md_path → 桶键 → sha256 | ✅ 唯一合法入口 | R'0 论域 |
| RustFS `published/*.md` **原始字节** + sha256 | 上游完备性证明（proof.json, gate_fail=false） | ✅ | 输入下界、源保真回指 |
| 《准则第2号》原文 PDF ×3 版本 | 〔2016〕31号 /〔2021〕15号 /〔2025〕3号 + 施行日 + **原文 sha256** | ✅ 外部 | E1 年报 schema |
| 《准则第3号》原文 PDF ×2 版本 | 〔2021〕16号 / 2025 新版 + 施行日 + **原文 sha256** | ✅ 外部（02/03 缺失） | E1 半年报 schema |
| 巨潮 / 深交所 **XBRL 实例文档** | as-filed，四级标记，五张报表 | ✅ 外部 | E2 表格主裁判 |
| 东方财富 / 同花顺量化 DB 报表项目值 | **快照 ID + 快照日期 + 字段口径版本** | ✅ 外部 | E2 交叉验证（01 原锚） |
| 申万行业分类**历史版本** | point-in-time 成分股变更史 | ✅ 外部 | R'2 cohort z-score（用当前分类回填 2018 = 前视偏差） |
| 交易所问询函原文 + 披露日期 + 代码 | 交易所披露页 | ✅ 外部 | E6 |
| 下期 ROE / 营收增长率实际值 | 同一交付表 / 量化 DB | ✅ 外部 | E3 |
| LM-2011 中文金融词典原文 + 语料衍生词典 | 词典文件 sha + 生成脚本 commit | ✅ 外部 | R'3 双轨 |
| recognition 既有资产：`report_heading`(907,705)、`heading_verdict`(19,183 裁定 / 17 类)、15 canonical sections、`report_structure` 序号连续性、`char_pos` 契约 | `C:\dev\ashare-bulletin-recognition` | ⚠️ **只读参考**，不进本 repo 运行时 | 复用判定语义，不复制实现 |
| `source/html/sina|cfi/*`、`.trash_20261109/*`、`sina_bulletin.db` | 已废弃 `ashare-bulletin` | ❌ 未授权；**需 Human Gate 变更 01 R'0 后才可采** | 03 误当作既成前提 |

### 3.2 工具

- **已有，不增依赖**：`psycopg2`（交付表）、`boto3`（RustFS GET）、`pandas`（canonical DataFrame）、`jieba`（分词，版本入 hash 锚）、`typer`、`pytest`。
- **最小增量**：`hashlib` + 自研**版本化归一化函数**（Unicode NFC / 空白折叠 / 实体解码 / 表格线性化）；`hypothesis`（属性测试不变量，如"删一行表格不得改变其他 slot 值"）；`Arelle`（XBRL 实例文档解析，仅在 E2 主裁判启用时）。
- **明确不引入主链路**：`ollama/qwen`（命题、表格摘要、引用语义确认）、`qdrant`、`sentence-transformers`、`spacy`、`networkx`、`camelot/pdfplumber`。理由：① 属另一个产品（RAG），01 一期范围是特征矩阵；② 破坏 E4 复现性（见 H）；③ 与 `frame-v2.md` 已定义的溯源字段重复。
- 若将来确需 LLM：模型权重 sha + `temperature=0` + prompt sha + 解码参数必须成为 hash 锚的**第五元**，且只做复核、不产出数值。

### 3.3 专业方法

法规版本时间轴（point-in-time）· slot 四元组 canonical 化 · 三表勾稽自校验（资产=负债+权益；货币资金期末=现金流量表期末现金；未分配利润勾稽）· 可回指 span（offset + XPath + sha）· 序号连续性 cn/ar 双主体系 · κ 仅作标注过程质控 + 三方仲裁 · 属性测试不变量 · 错误类型饱和抽样（sequential stopping）· 判别对（同 code/year/period 两源同字段，只差一个变量）· Heckman 两步（三态分层）· 卡方检验（时间不倒挂）。

---

## 4. 外部客观标准：恢复 01 原义，补上判定程序

**元规则**（新增，不加 E 编号）：
1. 锚必须带身份与版本：`E{n}@01-requirement.md:<sha256>:v1`；禁止裸标签跨文档复用。
2. **可反驳性**：每个 frame 必须能一键回到原文 verbatim span；做不到即判 fail，不进统计分母。
3. **判定程序版本化**：E 的判定函数本身进 git，其 commit 纳入 hash 锚；换判定程序必须重跑全部 E。

| 锚 | 01 原义（不变） | 外部身份（机器可校验） | 判定函数 | 通过条件 |
|----|----------------|----------------------|---------|---------|
| E1 | 章节完备性 = 准则当年版本 | 第2号/第3号各版文号 + 施行日 + 原文 sha256 | `reg_version(period, disclosure_date)` → 法定章节集；算 missing / extra / order；**三态缺失分别计数** | `NOT_DISCLOSED` 打监管 flag；`EXTRACTION_FAILURE` 判工程 fail；`NOT_APPLICABLE` 不算缺失。三者不得混计 |
| E2 | 表格与量化 DB 逐项对账 | XBRL 实例文档（主）+ 量化 DB 快照 ID/日期（交叉） | 规范化到 `(concept, period, scope, unit, value)`；逐项比对；分歧落 evidence 表 | 误差 ≤0.5% 或 ≤1 元；对账失败**不静默丢弃**（01 R'4） |
| E3 | 语气信号 → 下期业绩方向 | 下期实际 ROE / 营收增长率 | **时序外**检验（t 期特征预测 t+1，禁全样本拟合）+ 行业×年份固定效应 | 方向准确率 ≥60% 且显著优于基线；禁止使用 t 时刻未知信息 |
| E4 | byte-identical 重跑 | 四/五元 hash 锚 + 判定程序 commit | 同输入同版本重跑逐字节比矩阵 **且** 跑双路径收敛 | diff = 0 **且** canonical 元组收敛；仅 diff=0 不算通过 |
| E5 | 缺失机制非随机性 | 上游 proof.json 的 1,688 unobtainable 清单 + 三态计数 | Heckman 两步 / 等价校正；描述统计按三态分层 | λ 显著性可报告；`NOT_APPLICABLE` 不得计入样本选择偏差 |
| E6 | 问询函对齐 | 问询函原文 + 披露日期 | 高风险样本 vs 基线次年问询覆盖率，卡方 | p<0.05 且时间不倒挂 |

被 02/03 引入但**不纳入本 repo 验收**的指标：Recall@10、cell-level 人工准确率、Cohen's κ、引用覆盖率、多粒度提升 10%。它们服务于另一个产品的另一个消费者；若确需，另立下游 repo 的规格，不得覆盖 E1-E6 标签。

---

## 5. 重写后的需求 R'0-R'9（编号不变，只补判定程序）

> 每条 = 01 冻结原文（继续有效）+ 深化条款。任何深化条款与 01 冲突时，以 01 为准并走变更流程。

**R'0 论域与取数契约** — 冻结：2018+ / 72,705 MD / 交付表 + RustFS GET / 禁止直连 /backup。
深化：① 论域按 `period ∈ {2,4}` 分别绑定第3号/第2号准则版本；② 法规版本表为 `reg_version` 函数，产物带原文 sha256；③ `source/html/*`、trash 快照、`sina_bulletin.db` 在变更批准前**不是合法输入**，不得进入任何 unit；④ 上游 proof.json 与 1,688 unobtainable 清单作为只读证据纳管。

**R'1 章节 schema 对齐当年版本** — 冻结：输出 `chapter_compliance` 矩阵，缺节打监管违规 flag（E1）。
深化：① 年报/半年报双 schema，各自带文号与施行日；② schema 是法规原文的**可追溯派生**（原文 sha → 章节清单），禁止手敲 YAML；③ 2025-07-01 起适用新版，章节数与顺序随版本变化，不得硬编码"10 节"；④ 缺失三态化；⑤ 复用 recognition 已验证的序号连续性（cn/ar）与"一级标题识别 ≠ 一级标题分类"不变量作为**判定语义参考**，不复制实现；⑥ 非结构标题（如"小计"）由法定章节集排除，不得靠正则猜层级。

**R'2 句子级最小单元 + cohort z-score** — 冻结：任何文本特征同时输出 cohort z-score 与原始值。
深化：① cohort 用 **point-in-time 申万行业分类**（禁止用当前成分回填历史）；② 句子边界规则与分词器版本进 hash 锚；③ 每个特征可回指原文 span；④ 数值特征必须携带 `(concept, period, scope, unit)`，缺一即 fail。

**R'3 情感/语气双轨词典** — 冻结：LM-2011 中文金融词典 + 语料衍生 TF-IDF 词典；禁用通用 Hownet/NTUSD 作主信号。
深化：① 词典原文 sha + 衍生脚本 commit 纳入 hash 锚；② 衍生词典必须在**时序外**构造（不得用全期语料造 t 期特征）；③ 词典版本变更必须重跑 E3/E4。

**R'4 表格 → DataFrame → canonical → 外部对账** — 冻结：误差 ≤0.5% 或 ≤1 元；失败进 evidence 表，不静默丢弃（E2）。
深化：① XBRL 实例文档为主裁判，量化 DB 为交叉验证；② 三表勾稽作为**无需外部 DB 的自校验**先跑；③ 失败按类型归类（期间/口径/单位/主体/跨页/断行/造数），致命类 0 容忍；④ 任何数值 frame 无 verbatim span 即 fail；⑤ 复用 01 已有 evidence 表机制，不新建表。

**R'5 forward-looking 双通道** — 冻结：规则初筛 + LLM 复核，单独建子语料与子特征矩阵。
深化：① **LLM 只做复核，不产出任何数值/事实**；② 若启用，模型权重 sha + `temperature=0` + prompt sha + 解码参数成为 hash 锚第五元（recognition 实测 0.1 自一致率仅 50%）；③ 不可锚定时降级为纯规则通道并显式标注 `resolution_state`，不得静默使用不可复现结果。

**R'6 四元 hash 锚 + DVC** — 冻结：输入 MD sha set + 词典版本 + 分词器版本 + 管线 commit；byte-identical 可证（E4）。
深化：① 新增第五元（归一化函数 / LLM 版本 / 判定程序 commit，按实际启用项）；② byte-identical 是**必要非充分**条件，须同时通过双路径收敛；③ 归一化函数与判定函数版本化并公开；④ 每个 frame 的 provenance 复用 `frame-v2.md` 既有字段语义（`source_hash`/`start_offset`/`end_offset`/`semantic_path`/`resolution_state` 四态），**不自造枚举**。

**R'7（二期）缺失机制** — 冻结：1,688 unobtainable 进描述统计；回归须报告 Heckman 两步或等价校正（E5）。
深化：① 三态缺失分别建模，`NOT_APPLICABLE` 不参与选择偏差；② 抽取层的 `EXTRACTION_FAILURE` 必须单列，不得伪装成"公司未披露"。

**R'8（二期）信号有效性门禁** — 冻结：入主矩阵前证明与未来业绩方向相关 ≥60%（E3）。
深化：① 时序外评估；② 行业×年份固定效应；③ 特征不得使用 t 时刻未知信息；④ 评估脚本 commit 纳入 hash 锚。

**R'9（二期）监管印证抽检** — 冻结：高风险样本次年问询函覆盖率显著高于基线（卡方 p<0.05）（E6）。
深化：① 问询函披露日期必须晚于特征计算时点（防倒挂）；② 基线构造方式随报告落盘，防止挑基线调 p 值。

---

## 6. 停止规则（替代 03 的 9 阶段 / 29-49 天）

1. **唯一门禁**：任一 unit 完成后，先跑其绑定 E 的判定程序；不过不许合入（AGENTS.md 失控防御第 3 条）。不设"带着已知缺陷往上跑"的中间态。
2. **抽样停止规则**：按 (法规版本 × 板块 × point-in-time 行业 × 难度层) 分层，用**判别对**（同一 code/year/period、只差一个变量）持续抽，直到连续 k 份不产生新的失败类型即停，输出带置信界的覆盖结论。全量运行是生产行为，不是验证行为。
3. **不做 ROI 前置诊断实验**：03 Phase 1「先测结构丢失率 >15% 再决定 R''1 是否值得」是在未裁定取数合法性的前提下设计实验；前提未裁定时，实验结果不具规格效力。
4. **不做全量放行阶段**：全量只证明"没崩"，不证明"对"。

---

## 7. 与 01 的逐条 diff

| 项 | 01 现状 | 提案 | 类型 |
|----|--------|------|------|
| E1 | "§2 号准则当年版本" | 年报/半年报双准则 + 版本函数 + 原文 sha + 三态缺失 | 判定程序深化 |
| E2 | 量化 DB 对账 | 增 XBRL 主裁判、勾稽自校验、失败分类 | 判定程序深化 |
| E3 | ≥60% 方向准确率 | 增时序外 + 固定效应 + 防前视 | 判定程序深化 |
| E4 | byte-identical | 增可判定等价（双路径收敛）、第五元锚 | 判定程序深化 |
| E5 / E6 | Heckman / 卡方 | 增三态分层 / 时间不倒挂 | 判定程序深化 |
| R'1 | 10 节矩阵 | 版本相关章节集，取消硬编码节数 | 修正版本相关假设 |
| R'4 / R'6 | 已有 evidence 表 / 四元锚 | 明确复用既有字段语义，禁止自造枚举、禁止造数 | 铁律 4 落地 |
| 需求条目数 | 10 | **10（不变）** | — |
| 取数边界 | 交付表 + RustFS GET | **不变** | — |
| 02/03 | 自称 Authority | 降级为执行参考；R''/R'''、其 E1-E6 标签作废 | 权威收敛 |

---

## 8. 生效条件与禁止项

- 需 solution-architect 走变更流程 + Human Gate 批准（01 抬头："任何偏离须经 solution-architect 走变更流程并同步全部受影响方"；`agent-evidence-authority.md:48-68`：改变 authority / schema 语义属 Governor Gate）。
- 合入后需同步 `AGENTS.md`、README、02、03 的引用，消除 R''/R''' 与 E 标签歧义。
- **Agent 不得自行**：修改 01、恢复 trash、扩大取数边界、发明新 Requirement 代际、把审计事实当作需求授权（`ashare-project/README.md:109-112` "Agent 不能 invent project authority"）。
- 不修改上游 `nooshare-annual-semi`；两个参考仓库只读。

## 9. 立即可执行的第一步（不写解析代码、不扩数据）

1. 冻结**锚身份表**：把 01 的 E1-E6 标注为 `E{n}@01:<sha>:v1`，02/03 中同名标签改名或作废。
2. 建立**法规版本表**：`reg_version(period, disclosure_date)` → 文号 + 施行日 + 原文 sha256（含第3号）。
3. 补一份**消费者与维护规则契约**：谁读特征矩阵、读哪些列、schema 版本如何演进、何时判过期——否则 E1-E6 替消费者判定的合法性也无从锚定。

三项都是文档级、零依赖、可逆，且是后续任何 unit 能通过门禁的前置条件。

---

**END OF DOCUMENT**
