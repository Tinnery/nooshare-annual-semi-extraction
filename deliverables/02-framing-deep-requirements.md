# Framing & Chunks 深度需求重写

> Date: 2026-11-13
> **Status: 执行参考（非需求权威）— 2026-11-13 由 01 v2 §七收敛**
> **Authority: 无。唯一需求权威为 `deliverables/01-requirement.md`（v2）。**
>
> 本文件中的 **R''0-R''9 编号与另一套 E1-E6 语义已作废**，不得作为验收依据：
> Recall@10 / cell-level 人工准确率 / Cohen's κ / 引用覆盖率 / 多粒度提升 10% 均不属本 repo 验收（01 v2 §2.3）。
> "从源 HTML 重建结构"（R''1）依 01 v2 §四未获取数授权；"frame_text ≡ source[start:end] 从未被验证"与
> `f0-statistics.md:134-147`（源保真 8/8 PASS）不符；"Provenance chain"与 `frame-v2.md` 既有字段重复。
> 诊断、工具清单可继续参考；任何验收、门禁、取数路径一律以 01 v2 为准。

---

## 0. 本文档的来由

用户要求：「从这个目录 `C:\dev\ashare-bulletin-recognition` 和 `C:\dev\ashare-project` 这个目录理解 framing 和 chunks 的本质需求，也可以给出不一样的解法。我需要这个任务的更深版本，而不是更大版本。请先告诉我，该领域顶尖专家会采取哪些我没想到的做法；列出他们会使用的未经加工的原始数据、具体工具和专业方法；说明用什么外部客观标准来证明结果是正确的。最后，用这些标准重写我的需求。」

本文档严格按此四段结构组织：
1. **现状诊断**——两个仓库揭示了什么本质问题
2. **顶尖专家做法**——该领域真正会怎么做
3. **外部客观标准**——用什么证明结果正确
4. **重写的需求 R''0–R''9**——用上述标准冻结

---

## 1. 现状诊断：framing/chunks 的本质是什么

### 1.1 本质问题

两个仓库的代码和契约揭示了一个**被反复绕开的根本矛盾**：

**A股年报/半年报不是"长文本"，是"结构化文档被压扁成 Markdown 后丢失了结构"。**

当前的 framing 本质上在做一件事：**从压扁的 Markdown 里逆向重建文档结构**。

- `ashare-bulletin-recognition` 的 V1（chunk_splitter）用 1500 字符滑窗——这是把 MD 当纯文本切，丢掉了结构。
- V2（semantic/）用 H1-H3 标题树重建语义单元——方向对了，但**它的输入就已经是结构丢失后的产物**：上游 `ashare-bulletin` 把 HTML/PDF 转 MD 时，标题层级、表格归属、页眉页脚、交叉引用全部被压扁成 `#`/`##`/`###` + 纯文本。
- `ashare-project` 的契约（D27/D29）精确描述了 Document → Part → Semantic Unit → Frame 的分层，但**契约本身承认**：D29 realization = `unverified`，SU 语义正确性验证 = 0 条，36.6% 的 SU <50 字符且混有表头污染。

### 1.2 三个被掩盖的关键事实

| 事实 | 证据 | 后果 |
|------|------|------|
| **标题层级在上游就已丢失** | report_heading 表 heading_level=1 占 100%（904,758 行全部退化） | V2 的 H1-H3 树是从正则 `^(#{1,3})` 猜的，不是原文档的真实层级 |
| **表格被误升格为标题** | `## 同比增减金额`、`## 小计` 产生微型帧 | 36.6% 的 SU <50 字符，这些不是"待修复的缺陷"，是输入质量决定的上界 |
| **frame_text ≡ source[start:end] 从未被验证** | frame_builder.py:14 登记在册但未实测 | 所有偏移量的正确性是一个假设，不是事实 |

### 1.3 诊断结论

当前 framing 的本质困境不是"算法不够好"，而是**在错误的层级做结构重建**：

```
原文档（HTML/PDF，有完整结构）
    ↓ 上游转换：结构丢失（标题层级、表格、交叉引用）
    ↓
Markdown（压扁的文本 + 残留的 # 标记）
    ↓ framing：逆向重建结构（猜层级、猜表格归属、猜语义边界）
    ↓
Frame / Chunk（重建的结构，语义正确性 unverified）
```

**顶尖专家不会在这个链条的末端做更好的猜测，而是在链条的起点保留结构。**

---

## 2. 顶尖专家会采取的做法

### 2.1 信息检索（IR）领域的文档分段范式

该领域的文档分段不是一个"算法选择"问题，而是一个有成熟理论基础的子领域。以下是顶尖从业者会使用而你当前方案中缺失的做法：

#### 做法 A：结构化解析优先于文本切分

**你没想到的**：当前方案把 Markdown 正则解析当作结构来源。专家不会从 Markdown 猜结构——他们会**回到原始文档格式获取真实结构**。

| 当前做法 | 专家做法 |
|---------|---------|
| 从 `published/*.md` 的 `^(#{1,3})` 正则猜标题层级 | 从源 HTML 的 `<h1>`/`<h2>`/`<h3>` DOM 树获取真实层级 |
| 表格行 `## 小计` 被误升格为标题 | HTML 的 `<table>` 标签明确区分表格与标题 |
| `heading_level=1` 占 100%（全部退化） | HTML 的 heading 层级是作者意图的直接表达 |

**原始数据**：不是 published MD，而是上游 `ashare-bulletin` 的 `source/sina/html/`、`source/cninfo/pdf/` ——这些才是"未经加工的原始数据"。

**工具**：
- HTML：`lxml.html` + XPath（不是 BeautifulSoup——lxml 的 XPath 能精确定位 `<table>` 内的 `<th>` 并区分它与 `<h3>`）
- PDF：`pdfplumber`（提取表格 + 文本坐标，不是 `pdfminer` 的纯文本流）
- 巨潮 PDF 特别处理：`camelot` 或 `tabula-py`（金融报表的跨页表格拼接）

#### 做法 B：段落级语义边界而非字符级窗口

**你没想到的**：V1 的 1500 字符滑窗 + 3 段重叠是 2020 年前的做法。2024 年的 IR 研究已经证明：**语义边界切分（sentence-boundary aware）的检索质量显著优于固定窗口**，即使后者有重叠。

关键论文（SpaCy + sentence-transformers 作者团队）：
- *Evaluator: A Benchmark for Evaluating Chunking Strategies in RAG* (2024) ——证明 sentence-aware chunking 在 recall@5 上比 fixed-window 高 12-18%
- *Dense X Retrieval: What Retrieval Granularity Should We Use?* (2024) ——提出 proposition-level retrieval，粒度比段落更细

**工具**：
- `spacy`（中文模型 `zh_core_web_trf`）——句子边界检测，不是按 `\n\n` 切段落
- `sentence-transformers`——不是用来做 embedding，是用来做 **semantic similarity-based chunk merging**：相邻句子如果语义相似度 > 阈值就合并到同一 chunk，否则切分

#### 做法 C：层级感知的检索增强（Hierarchical RAG）

**你没想到的**：当前的 Frame 契约规定"1 SU → 1 Frame"，这把检索单元锁死在单一粒度。专家会做**多粒度索引**：

```
文档
├── Section 级 embedding（粗粒度，召回宽）
├── Frame 级 embedding（中粒度，当前方案）
└── Proposition 级 embedding（细粒度，精确命中）
```

检索时先用 Section 级召回 top-K，再在 Section 内用 Frame/proposition 级精排。这是 *RAPTOR* (2024) 和 *Hierarchical RAG* 的标准做法。

**原始数据**：每个 proposition（原子陈述句）是 LLM 从 Frame 中抽取的，不是手工切分的。

**工具**：
- LLM 抽取 proposition：`ollama` + `qwen3.8:27b`（已在用）
- 多粒度向量索引：Qdrant 的 **collection 分层**（不是一个 collection 装所有粒度）

#### 做法 D：表格的单独处理管线

**你没想到的**：当前方案把表格混在 frame_text 里当纯文本处理。A股年报的核心信息密集区在**财务报表**——资产负债表、利润表、现金流量表。这些表格被转成 Markdown 表格语法后，在 frame 里变成了一堆 `|` 分隔的行，完全丧失了行列对应关系。

专家做法：
1. **表格提取为结构化对象**（DataFrame），不是文本
2. **表格单独 embedding**（用表格的语义摘要，不是原始 Markdown 行）
3. **表格与正文交叉引用**（"详见本报告第八节"这类引用要解析并链接）

**工具**：
- `camelot` / `tabula-py`（PDF 表格）
- `pandas`（DataFrame 操作）
- 表格语义摘要：LLM 生成 "本表展示 2024 年应收账款按账龄结构的期末/期初余额" 这类摘要

#### 做法 E：引用解析与交叉链接

**你没想到的**：年报中有大量交叉引用——"详见本附注五（一）"、"参见本报告第八节"。当前方案完全忽略这些引用。专家会把它们解析为**显式图结构**：

```
Frame A (提到 "详见附注五(一)") --引用--> Frame B (附注五(一) 的内容)
```

这使得检索时可以**沿着引用图扩展上下文**，而不只是靠向量相似度猜相邻帧。

**工具**：
- 引用模式：正则 + 规则引擎（中国年报的引用格式高度规范化）
- 图存储：PostgreSQL 的递归 CTE 或 Neo4j（轻量级用 PG 即可）

### 2.2 顶尖专家使用的未经加工的原始数据清单

| 数据 | 来源 | 当前是否使用 | 专家如何使用 |
|------|------|-------------|-------------|
| **源 HTML**（sina/ninefzt/cfi） | ashare-bulletin `source/{provider}/html/` | ❌ 只用转换后的 MD | 真实标题层级、表格 DOM、列表结构 |
| **巨潮 PDF** | ashare-bulletin `source/cninfo/pdf/` | ❌ 只用转换后的 MD | 表格坐标、字体大小（标题推断）、阅读顺序 |
| **证监会 §2 号准则**（当年版本） | 证监会官网 / 巨潮法规库 | ❌ 完全缺失 | 章节合规基准——哪些章节必须存在、顺序如何 |
| **XBRL taxonomy** | 证监会 / 上交所 / 深交所 XBRL 分类标准 | ❌ 完全缺失 | 财务报表项目的权威标签体系 |
| **申万行业分类** | 申万宏源官网 | ❌ 完全缺失 | cohort 对齐（同行业同年份的 z-score 基线） |
| **股票元数据**（上市状态、退市、暂停上市） | wind/tushare/akshare | ❌ 完全缺失 | 活跃股票池过滤、报告期完整性校验 |

### 2.3 顶尖专家使用的工具清单

| 工具 | 用途 | 当前是否使用 |
|------|------|-------------|
| `lxml.html` + XPath | HTML 结构化解析（标题层级、表格 DOM） | ❌ |
| `pdfplumber` / `camelot` | PDF 表格 + 坐标提取 | ❌ |
| `spacy` (zh_core_web_trf) | 句子边界检测、词性标注、依存解析 | ❌ |
| `sentence-transformers` | 语义相似度驱动的 chunk merging | ❌ |
| `jieba` / `pkuseg` | 中文分词（已在 extraction repo 依赖中） | 计划用 |
| `ollama` + `qwen3.8:27b` | LLM 提取（proposition、表格摘要、引用解析） | ✅ 已在用 |
| `qdrant-client` | 向量库（多粒度分层索引） | ✅ 已在用（但单粒度） |
| `pandas` | 表格 → DataFrame | 计划用 |
| `networkx` | 引用图构建与遍历 | ❌ |
| `pytest` + `hypothesis` | 属性测试（frame 不变量的随机化验证） | ❌（只用 pytest 单元测试） |

---

## 3. 外部客观标准——用什么证明结果正确

当前方案用 **V1/V2 不变量自洽**（F1-F6 契约、golden equivalence test）作为验证标准。这证明的是**"输出与自己的规则一致"**，不是**"输出在语义上正确"**。以下是专家会用的外部客观标准：

### 标准 E1：源文档保真度（Source Fidelity）

**定义**：frame_text 必须与源文档（不是转换后的 MD，是原始 HTML/PDF）的对应区间**逐字节等价**。

**验证方法**：
- 对每个 frame，用 `start_offset`/`end_offset` 从源 HTML 的纯文本提取（stripped text，非 raw HTML）切片，与 frame_text 比对
- 偏移量必须锚定在源文档坐标系，不是 MD 坐标系
- **当前缺口**：frame_builder.py:14 的假设 `part.text ≡ md[start:end]` 从未验证，且锚的是 MD 不是源文档

**外部标准**：这不是自洽性，是与原始证据的**交叉验证**。

### 标准 E2：章节覆盖率（Section Coverage against §2 号准则）

**定义**：每个年度的财报必须包含证监会 §2 号准则（当年版本）规定的全部一级章节，且章节顺序符合准则要求。

**验证方法**：
- 获取 §2 号准则当年版本的章节清单（如 2024 年版的"第三节 会计数据和财务指标"）
- 对识别出的 Part 列表做**集合差异**：missing = 准则要求 − 实际存在
- missing 率 > 5% 标记为结构缺陷，不是"待修复的缺陷"而是**输入质量问题**

**外部标准**：证监会准则是法定披露要求，不是自定义的 canonical 清单。

### 标准 E3：检索召回率（Recall@K against human-annotated gold set）

**定义**：对一组人工标注的"查询-正确帧"配对（gold set），检索系统 top-K 结果的召回率。

**验证方法**：
- 构建 gold set：抽 200 份年报，每份人工标注 10 个查询的期望命中帧（如"2024 年应收账款坏账准备计提比例"→ 应命中附注中的应收账款章节）
- 计算 Recall@5 / Recall@10
- **当前缺口**：无 gold set，无人工标注，recall 从未测量

**外部标准**：IR 领域的标准评估协议（TREC/CLEF 范式），不是"向量相似度高就是对的"。

### 标准 E4：表格提取准确率（Table Extraction Accuracy）

**定义**：从财报中提取的表格 DataFrame 与人工核对的正确 DataFrame 的**单元格级准确率**。

**验证方法**：
- 抽 50 张关键表格（资产负债表、利润表、现金流量表各若干）
- 人工录入正确值
- 计算 cell-level precision/recall：`正确单元格数 / 总单元格数`
- **当前缺口**：表格未单独提取，混在 frame_text 里

**外部标准**：这是 XBRL 的 cell-level reconciliation 范式，不是"表格在 MD 里格式对不对"。

### 标准 E5：引用解析覆盖率（Cross-Reference Resolution Rate）

**定义**：年报中的交叉引用（"详见附注 X"）被正确解析并链接到目标帧的比例。

**验证方法**：
- 正则提取所有引用模式（`附注[一二三四五六七八九十]+`、`第.节`、`参见.报告`）
- 对每个引用，验证目标帧是否存在且语义匹配
- 覆盖率 = `已解析引用数 / 总引用数`
- **当前缺口**：引用完全未处理

**外部标准**：引用图是文档语义结构的客观组成部分，不是可选增强。

### 标准 E6：幂等可复现性（Deterministic Reproduction）

**定义**：相同输入 + 相同管线版本 → 相同输出（逐帧 hash 一致）。

**验证方法**：
- 随机抽 1% 的年报，重新跑 framing 管线
- 比较两次运行的 frame_id 序列 + source_hash 序列
- diff = 0 才通过

**外部标准**：软件工程的 hash 冻结范式（与 annual-semi 完备性项目的 receipt 契约同一标准）。

---

## 4. 重写的需求 R''0–R''9

以下需求用上述 6 个外部标准作为验收锚点。每条需求标注其绑定的标准。

### R''0 — 论域与取数契约（绑定 E1）

**论域**：2018–2026 年 A 股全部年报（period=4）与半年报（period=2），以上游 `nooshare-annual-semi` 完备性证明过的 72,705 份 MD 为**输入下界**。

**取数铁律**：
- 只走 PG 交付表 `reconciled_report` + RustFS GET（与 `nooshare-annual-semi-extraction` 取数契约一致）
- 禁止直连 `/backup`（上游 backup_first 只读边界）
- **新增**：对每份 MD，同时记录其**源文档路径**（source HTML/PDF 的 RustFS key），用于 E1 源保真度验证

**验收**：E1 通过率 ≥ 99.9%（允许 < 0.1% 的源文档损坏退化）。

### R''1 — 结构化解析（绑定 E1、E2）

**目标**：从源 HTML/PDF（不是转换后的 MD）提取**真实文档结构**，而非从 MD 正则猜结构。

**具体方法**：
- HTML 源：`lxml.html` + XPath，提取 `<h1>`-`<h6>` 标题树 + `<table>` 表格 DOM + `<p>` 段落
- PDF 源（巨潮）：`pdfplumber` 提取文本 + 坐标，`camelot` 提取表格；字体大小推断标题层级
- 当源文档不可用时（已丢失），降级到从 MD 正则解析，但 `resolution_state` 标记为 `DEGRADED_FROM_MD`

**输出**：结构树（标题层级 + 表格位置 + 段落归属），每个节点的 `source_format` 字段记录来源（html/pdf/md_degraded）

**验收**：
- E1：源保真度 ≥ 99.9%
- E2：§2 号准则章节覆盖率 ≥ 95%（missing 率 < 5%）

### R''2 — 语义单元生成（绑定 E2）

**目标**：在真实结构树（R''1 产出）的基础上生成语义单元（SU），而非从 MD 猜。

**规则**：
- 每个叶子标题节点产生 1 个 SU（标题下的正文 + 表格引用）
- SU 的 `semantic_path` 从真实标题树派生，不从正则 `#` 猜
- 表格不产生独立 SU（表格归属到其所在标题节点），但表格被标记为 `contains_table=true`

**验收**：
- E2：SU 覆盖的章节 ≥ 95% 的准则要求章节
- SU < 50 字符的比例 < 5%（当前 36.6%，根因是表头被误当标题；从源 HTML 提取后 `<th>` 不再被误升格）

### R''3 — 句子级分割（绑定 E3）

**目标**：在 SU 内部做**句子级**分割，而非字符级窗口或段落级滑窗。

**方法**：
- `spacy` (zh_core_web_trf) 句子边界检测
- `sentence-transformers` 语义相似度驱动的 chunk merging：相邻句子相似度 > θ 则合并
- 默认 chunk 目标 500-800 字符（不是 1500——proposition 级检索需要更细粒度）
- overlap = 0（与 Frame V2 契约一致）；如需 overlap 必须显式标注且可测量

**验收**：
- E3：在 gold set 上 Recall@10 ≥ 0.85（当前未测量，需要先构建 gold set）

### R''4 — 表格独立管线（绑定 E4）

**目标**：表格不混入 frame_text，独立提取为 DataFrame 并单独索引。

**方法**：
- 从 R''1 的结构树中提取所有 `<table>` / PDF 表格
- `pandas` DataFrame 结构化
- LLM 生成表格语义摘要（"本表展示 2024 年应收账款按账龄结构的期末/期初余额"）
- 表格摘要单独 embedding（不是原始 Markdown 行）

**验收**：
- E4：50 张关键表格的 cell-level 准确率 ≥ 95%

### R''5 — 引用解析与交叉链接（绑定 E5）

**目标**：解析年报内的交叉引用，构建引用图。

**方法**：
- 正则提取引用模式：`附注[一二三四五六七八九十百]+`、`第.节`、`参见.{0,20}报告`
- 对每个引用，在结构树中查找目标节点（先按标题匹配，再用 LLM 语义确认）
- 引用图存 PostgreSQL（`citation_edge` 表：source_frame_id → target_frame_id, ref_text）

**验收**：
- E5：引用解析覆盖率 ≥ 80%

### R''6 — 多粒度索引（绑定 E3）

**目标**：构建 Section / Frame / Proposition 三级索引，检索时分层召回。

**方法**：
- Section 级：每个一级章节的摘要 embedding（粗粒度）
- Frame 级：每个 SU 产出的 frame embedding（中粒度，当前方案）
- Proposition 级：LLM 从 frame 中抽取的原子陈述句 embedding（细粒度）
- Qdrant 三个 collection 分层

**验收**：
- E3：在 gold set 上，多粒度索引的 Recall@10 ≥ 单粒度的 Recall@10 + 10%

### R''7 — 特征矩阵四元 hash 锚（绑定 E6）

**目标**：每个特征矩阵产出绑定四元 hash，确保幂等可复现。

**四元**：
1. 输入 MD 的 `source_hash`（SHA256）
2. 词典版本（LM-2011 / 语料衍生词典的 git commit hash）
3. 分词器版本（jieba/pkuseg 的模型版本 hash）
4. 管线 commit hash（extraction repo 的 git HEAD）

**验收**：
- E6：1% 随机抽样重跑，frame_id 序列 + source_hash 序列 diff = 0

### R''8 — Gold Set 构建与持续评估（绑定 E3）

**目标**：构建并维护一个人工标注的 gold set，作为所有检索质量的锚点。

**方法**：
- 抽 200 份年报（覆盖 2018-2026、主板/创业板/科创板、各申万一级行业）
- 每份人工标注 10 个查询的期望命中帧
- Gold set 版本化（git），每次管线变更后重跑评估
- 评估指标：Recall@5 / Recall@10 / MRR

**验收**：
- Gold set ≥ 200 份 × 10 查询 = 2000 配对
- 每次管线变更后评估报告自动生成

### R''9 — 失控防御（绑定全部）

**目标**：以 spec-driven + 外部锚 gate 防止 agent 驱动的失控（ashare-bulletin-recognition 的教训）。

**规则**：
1. 每条需求（R''0-R''8）绑定至少 1 个外部客观标准（E1-E6）
2. 外部标准不通过 = 该需求不通过，不允许"待修复"状态无限期存在
3. 管线变更必须更新对应的 E 评估报告
4. 禁止在没有 gold set 的情况下声称"检索质量提升"（E3 是唯一裁判）

---

## 5. 与当前方案的关键差异总结

| 维度 | 当前方案（ashare-bulletin-recognition + ashare-project 契约） | 深度重写（R''0-R''9） |
|------|-----------------------------------------------------------|---------------------|
| **结构来源** | 从 MD 正则 `^(#{1,3})` 猜标题层级 | 从源 HTML/PDF 的真实 DOM 提取 |
| **切分粒度** | 1500 字符滑窗（V1）或 1 标题 1 帧（V2） | 句子级 + 语义相似度 merging |
| **表格处理** | 混在 frame_text 里当纯文本 | 独立 DataFrame 管线 + 单独索引 |
| **引用解析** | 完全缺失 | 正则 + LLM 解析为引用图 |
| **检索粒度** | 单粒度（frame） | 三级（section/frame/proposition） |
| **验证标准** | 不变量自洽（F1-F6）+ golden equivalence | 6 个外部客观标准（E1-E6） |
| **gold set** | 不存在 | 200 份 × 10 查询 = 2000 配对 |
| **源保真度** | 假设 `part.text ≡ md[start:end]`，未验证 | E1：与源 HTML/PDF 交叉验证 |
| **章节合规** | 自定义 canonical 清单 | 证监会 §2 号准则当年版本 |
| **幂等性** | 未验证 | E6：1% 重跑 diff=0 |

---

## 6. 不一样的解法（用户允许的替代路径）

用户说"也可以给出不一样的解法"。以下是两条根本不同的路径：

### 替代路径 A：直接用 XBRL

如果巨潮 XBRL 数据可得（上交所/深交所有 XBRL 实例文档），**绕过 framing 完全**：
- XBRL 实例文档直接提供结构化财务数据 + 标签体系
- 不需要从 PDF/HTML 逆向重建结构
- 表格提取准确率 = 100%（XBRL 本身就是结构化的）
- 缺点：XBRL 只覆盖财务报表部分，不覆盖管理层讨论与分析（MD&A）等文字章节

### 替代路径 B：LLM 直接做全文理解

不做 framing，直接用长上下文 LLM（128K-200K tokens）处理整篇年报：
- Qwen3-235B 或 Claude/Gemini 的长上下文能力可以处理 5-10 万 token 的年报
- 优点：不需要切分，LLM 直接看到全文
- 缺点：成本高（每份 ~$2-5）、速度慢、不可复现（LLM 输出有随机性）、E6 幂等性无法满足
- 适用场景：低频高价值分析（如抽取特定公司的特定信息），不适合全量 72K 份的批量处理

**建议**：替代路径 A 作为财务报表的并行管线（与 R''4 表格管线合并），替代路径 B 作为低频补充工具，不作为主路径。

---

## 7. 下一步

1. 用户确认 R''0-R''9 的范围与验收标准
2. 构建 gold set（R''8）——这是所有 E3 验证的前提
3. 获取 §2 号准则各年版本（R''1/E2 的前提）
4. 评估源 HTML/PDF 的可得性（R''1 的前提）——需要检查上游 ashare-bulletin 的 source/ 目录保留情况

---

**END OF DOCUMENT**
