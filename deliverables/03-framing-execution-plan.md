# Framing & Chunks 落地策略与执行手册

> Date: 2026-11-13
> **Status: 历史执行草案（非需求权威）— 2026-11-13 由 01 v2 §七收敛**
> **Authority: 无。唯一需求权威为 `deliverables/01-requirement.md`（v2）。**
>
> 作废条款：R'''0-R'''7 编号、9 阶段关键路径与 29-49 天估算、**Phase 1 结构丢失诊断实验**、
> `source/html/sina|cfi` / ninefzt / `.trash_20261109` / `sina_bulletin.db` 的取数与 trash 恢复写入、
> ollama / qdrant / spacy / sentence-transformers / networkx 主链路。
> 依据：01 v2 §四（取数边界裁定，实然不证应然）、§五（停止规则）、§2.3（E1-E6 判定程序）。
> 本文件保留为执行思路的历史记录，**不得据此启动任何 Phase**。

---

## 0. 本文档定位

R''0-R''9 定义了"做什么"和"用什么标准验收"。本文档定义"怎么做"——可落地的执行策略。

用户要求"更深版本，而不是更大版本"。这意味着：
- 不增加需求条目（R''0-R''9 已冻结）
- 深化每条需求的执行路径：前置条件、工具链、中间产物、硬门禁
- 找出**关键路径**（串行不可跳过的步骤）与**可并行步骤**
- 诚实标注哪些可以做、哪些需要前置投资、哪些应该推迟

---

## 1. 顶尖专家在执行层面会采取的做法（你没想到的）

### 做法 F：先测量结构丢失量，再决定策略

**你没想到的**：在投入 R''1（源 HTML 解析）之前，先做一个**诊断实验**：对 100 份报告，同时解析源 HTML 和转换后的 MD，测量两者提取出的标题树有多大差异。这告诉你"结构丢失"到底有多严重——如果差异 < 5%，R''1 的 ROI 就不足以支撑重写解析器；如果差异 > 30%，R''1 就是第一优先级。

**方法**：
- 对 100 份报告，分别用 lxml 从源 HTML 提取标题树 + 从 MD 正则提取标题树
- 计算标题集合差异：`diff = |HTML_titles − MD_titles| / |HTML_titles|`
- 同时测量表格误升格率：HTML 的 `<table>` 内有多少 `<th>` 被 MD 转换器变成了 `##`

**产出**：一份 1 页的结构丢失诊断报告，包含"是否值得做 R''1"的量化判断

### 做法 G：Schema-guided 解析（自顶向下）

**你没想到的**：当前所有方案都是 bottom-up（从文档内容猜结构）。专家用 top-down：先加载证监会 §2 号准则的章节 schema（"第三节 会计数据和财务指标"必须存在），然后用 schema 去匹配文档中的标题——匹配上的标记为 `EXPECTED`，匹配不上的标记为 `UNEXPECTED`，缺失的标记为 `MISSING`。

这比 bottom-up 的优势：
- `MISSING` 章节立刻触发 E2（章节覆盖率）违规，不需要等全量处理
- `UNEXPECTED` 标题（如 `## 小计`）可以用 schema 过滤掉——"这不在准则规定的章节清单里，所以不是结构标题"
- 表格误升格问题在 schema 层面就解决了——schema 里没有"小计"这个章节

### 做法 H：增量验证环（10 → 100 → 1000 → 全量）

**你没想到的**：不要先建基础设施再跑全量。专家的做法是：
1. **10 份原型**：手动选 10 份覆盖不同难度的报告，手工验证每一步的产出
2. **100 份扩展**：用 E1-E6 量化测量，通过门禁后继续
3. **1000 份规模化**：验证管线在规模化下的性能和稳定性
4. **全量**：只有在 1000 份全部门禁通过后才放行

每个阶段有**硬门禁**：不通过就停下来修，不带着已知缺陷往上跑。

### 做法 I：Provenance chain 作为一等公民

**你没想到的**：当前方案的 frame 只记录 `source_hash`（MD 的 hash）。专家会在每个 frame 上记录完整的**溯源链**：

```
frame.provenance = {
    md_source_hash: "sha256:...",          // MD 文件 hash（当前已有）
    source_html_key: "source/html/sina/600000/10000002.html",  // 源 HTML 路径
    source_provider: "sina",               // 数据源
    extraction_method: "lxml_xpath",       // 提取方法
    resolution_state: "UNAMBIGUOUS",       // 结构解析状态
    schema_match: "EXPECTED",              // schema 匹配结果
}
```

这使得 E1（源保真度）在任何时候都可审计——不需要单独跑验证脚本，直接查 provenance chain。

### 做法 J：对抗性测试集（不是随机抽样）

**你没想到的**：Gold set 不是随机抽 200 份。专家会**故意选最难的案例**：
- 标题层级最混乱的（H1→H3 跳级、无 H1 只有 H2）
- 表格最密集的（财务报表附注，数十张表格）
- 篇幅最长的（>200KB MD）
- 套话最多的（前面 5 页全是"全体员工团结拼搏"）
- 结构缺失的（缺"财务报告"章节的残缺报告）

对抗性测试集的价值：如果管线能处理最难的 10%，就能处理剩下的 90%。

---

## 2. 未经加工的原始数据清单（执行版）

| 数据 | 位置 | 可得性 | 用途 |
|------|------|--------|------|
| **sina 源 HTML** | RustFS `source/html/sina/{code}/{native_id}.html`，>61K 文件 | ✅ 可直接 GET | R''1 结构化解析 |
| **cfi 源 HTML** | RustFS `source/html/cfi/{code}/p{date+seq}.html`，>61K 文件 | ✅ 可直接 GET | R''1 结构化解析 |
| **ninefzt 源 HTML** | trash `/source/.trash_20261109/ashare-bulletin/ninefzt/html/`，187K 文件，39G | ⚠️ 需从 trash 恢复到 RustFS | R''1 扩展覆盖 |
| **sina PDF** | trash `sina/pdf/`，15K 文件 | ⚠️ 在 trash 中 | 表格提取的 PDF 路径 |
| **sina_bulletin.db** | trash `/source/.trash_20261109/metadata/sina_bulletin.db`，2.4G | ✅ immutable 模式可读 | native_id↔stock_code↔year/quarter 映射 |
| **published MD**（72,705 份） | RustFS `published/{code}/{code}_{year}_{period}.md` | ✅ 完备性已证明 | R''0 输入下界 |
| **§2 号准则** | 证监会官网 / 巨潮法规库 | 🔍 需获取各年版本 | R''2/E2 章节合规基准 |
| **申万行业分类** | 申万宏源官网 | 🔍 需获取 | Gold set 分层抽样 |
| **XBRL taxonomy** | 上交所/深交所 XBRL 分类标准 | 🔍 需确认可得性 | 替代路径 A（财务报表直取） |

---

## 3. 工具链清单（执行版）

### 3.1 已有工具（复用）

| 工具 | 版本 | 当前用途 | 执行计划中的用途 |
|------|------|---------|----------------|
| `uv` | 0.13.7 | 包管理 | 依赖管理 + 虚拟环境 |
| `psycopg2` | 2.9+ | PG 驱动 | 读交付表 + 写结构化产出 |
| `boto3` | 1.34+ | S3 客户端 | RustFS GET 源 HTML + published MD |
| `typer` | 0.12+ | CLI | 管线入口 |
| `ollama` + `qwen3.8:27b` | — | LLM | Proposition 抽取 + 表格摘要 + 引用语义确认 |
| `qdrant-client` | 1.7+ | 向量库 | 多粒度索引 |
| `pytest` | 8.0+ | 测试 | 单元 + 集成 |

### 3.2 新增工具

| 工具 | 用途 | 安装方式 |
|------|------|---------|
| `lxml` | HTML 结构化解析 + XPath | `uv add lxml` |
| `pdfplumber` | PDF 文本+坐标提取 | `uv add pdfplumber` |
| `spacy` + `zh_core_web_trf` | 句子边界检测 + 词性 | `uv add spacy && uv run python -m spacy download zh_core_web_trf` |
| `sentence-transformers` | 语义相似度 chunk merging | `uv add sentence-transformers` |
| `networkx` | 引用图构建与遍历 | `uv add networkx` |
| `hypothesis` | 属性测试（frame 不变量随机验证） | `uv add --dev hypothesis` |

---

## 4. 执行策略：关键路径与阶段

### 4.1 关键路径分析

```
Phase 0: 源数据审计 ✅（已完成）
    │
    ▼
Phase 1: 结构丢失诊断实验（做法 F）
    │  产出：1页诊断报告，量化"是否值得做 R''1"
    │  门禁：结构丢失差异 > 15% → 继续；< 15% → 重新评估策略
    │
    ▼
Phase 2: Gold set 构建（R''8，做法 J）
    │  产出：200份对抗性选样的标注集
    │  门禁：2000配对完成 + 标注一致性 Cohen's κ ≥ 0.7
    │  注意：这是所有 E3 验证的前提，必须最先做
    │
    ▼
Phase 3: §2 号准则 schema 构建（R''2/E2，做法 G）
    │  产出：2018-2026 各年章节 schema（YAML）
    │  门禁：每年 schema 覆盖 ≥ 10 个必须章节
    │
    ▼
Phase 4: 源 HTML 结构化解析器（R''1，做法 A+I）
    │  产出：lxml + XPath 解析器，输出结构树 + provenance chain
    │  门禁：10份原型 E1 通过率 ≥ 99%
    │  门禁：100份扩展 E1 ≥ 99.9% + E2 ≥ 95%
    │
    ▼
Phase 5: 句子级分割 + 语义 merging（R''3，做法 B）
    │  产出：spacy + sentence-transformers 分割器
    │  门禁：Gold set 上 Recall@10 ≥ 0.85
    │
    ├─── Phase 6a: 表格独立管线（R''4，做法 D）        ┐
 │    │  门禁：50张表格 cell-level ≥ 95%              │
 │    │                                               │ 可并行
 ├─── Phase 6b: 引用解析（R''5，做法 E）              │
 │    │  门禁：引用覆盖率 ≥ 80%                        ┘
 │
 ▼
Phase 7: 多粒度索引（R''6，做法 C）
    │  产出：Section/Frame/Proposition 三级 Qdrant collection
    │  门禁：多粒度 Recall@10 ≥ 单粒度 + 10%
    │
    ▼
Phase 8: Hash 锚 + 幂等复现（R''7/E6）
    │  产出：四元 hash 锚定 + 1% 重跑验证
    │  门禁：diff = 0
    │
    ▼
Phase 9: 全量放行（1000 → 全量 72K）
    门禁：Phase 4-8 全部通过 + 1000份规模化无错误
```

### 4.2 并行机会

| 可并行的阶段 | 条件 | 说明 |
|-------------|------|------|
| Phase 2 (Gold set) ∥ Phase 3 (§2 schema) | 无依赖 | Gold set 标注和 schema 获取可同时进行 |
| Phase 6a (表格) ∥ Phase 6b (引用) | Phase 4 完成 | 表格管线和引用解析互不依赖 |
| Phase 7 (多粒度) ∥ Phase 8 (hash锚) | Phase 5 完成 | 索引构建和 hash 设计可同时推进 |

### 4.3 可推迟项

| 推迟项 | 原因 | 何时激活 |
|--------|------|---------|
| ninefzt 源 HTML 恢复 | sina+cfi 已覆盖 >122K，ninefzt 是增量 | Phase 4 在 sina+cfi 上验证后 |
| XBRL 替代路径 | 需确认 taxonomy 可得性 | Phase 6a 表格管线遇到瓶颈时 |
| 长上下文 LLM 全文理解 | 低频高价值，不影响主路径 | 需要时单独使用 |
| cninfo PDF 源恢复 | 仅 65 份转换后，源 PDF 基本缺失 | 覆盖最弱，优先级最低 |

---

## 5. 执行手册：每阶段的详细步骤

### Phase 1: 结构丢失诊断实验（1-2 天）

**目的**：量化 HTML→MD 转换丢失了多少结构，决定 R''1 是否值得。

**步骤**：
1. 从 RustFS `published/` 随机抽 100 份 MD
2. 对每份 MD，通过 `sina_bulletin.db` 的 `periodic_report` 表反查对应的源 HTML native_id
3. 从 RustFS `source/html/sina/{code}/{native_id}.html` GET 源 HTML
4. 对每份源 HTML 用 `lxml.html` + XPath `//h1|//h2|//h3|//h4` 提取标题树
5. 对每份 MD 用正则 `^(#{1,3})\s+(.+)$` 提取标题树
6. 计算差异矩阵：
   - `title_diff_rate` = `|HTML_titles - MD_titles| / |HTML_titles|`
   - `table_as_heading_count` = HTML `<table>` 内被 MD 转成 `##` 的 `<th>` 数量
   - `level_collapse_rate` = HTML 有多级标题但 MD 全部退化成 `#` 的比例

**产出**：`deliverables/diag-01-structure-loss.md`（1 页诊断报告）

**门禁**：
- `title_diff_rate` 均值 > 15% → R''1 值得做，继续
- `title_diff_rate` 均值 < 15% → 停下，重新评估 R''1 的 ROI

### Phase 2: Gold set 构建（3-5 天）

**目的**：构建人工标注的"查询-正确帧"配对集，作为 E3 的唯一裁判。

**步骤**：
1. **分层抽样**：从 72,705 份中选 200 份
   - 年份分层：2018-2026 每年 ~22 份
   - 交易所分层：上交所:深交所:北交所 ≈ 6:3:1
   - 行业分层：申万一级行业均匀覆盖
   - **对抗性强化**（做法 J）：额外加入 20 份最难案例（标题混乱/表格密集/结构缺失）

2. **查询设计**：每份报告 10 个查询
   - 3 个事实型（"2024年营业收入是多少"）
   - 3 个分析型（"应收账款坏账准备计提依据"）
   - 2 个比较型（"与上年相比研发投入变化"）
   - 2 个前瞻型（"公司对未来一年的经营计划"）

3. **标注**：对每个查询，人工在原文中标注期望命中的帧/段落
   - 标注工具：简单 JSON 标注文件（不需要复杂 UI）
   - 每个标注包含：query, expected_frame_text, expected_section_path

4. **一致性校验**：双人标注 20% 样本，计算 Cohen's κ

**产出**：`gold_set/gold_set_v1.jsonl`（2000 配对）+ `gold_set/annotation_guide.md`

**门禁**：
- 2000 配对完成
- Cohen's κ ≥ 0.7（标注一致性）

### Phase 3: §2 号准则 schema 构建（2-3 天）

**目的**：获取证监会 §2 号准则各年版本，构建章节 schema。

**步骤**：
1. 获取 2018-2026 年 §2 号准则（*公开发行证券的公司信息披露内容与格式准则第2号——年度报告*）
   - 来源：证监会官网法规库 / 巨潮法规网
   - 注意：2021-2022 有修订版，需确认各年适用的版本

2. 对每个版本，提取必须章节清单：
   ```yaml
   # schema/2024.yaml
   year: 2024
   required_sections:
     - {title: "第二节 公司简介和主要财务指标", level: 1, required: true}
     - {title: "第三节 管理层讨论与分析", level: 1, required: true}
     - {title: "第四节 公司治理", level: 1, required: true}
     - {title: "第五节 环境和社会责任", level: 1, required: true}
     - {title: "第六节 重要事项", level: 1, required: true}
     - {title: "第七节 股份变动及股东情况", level: 1, required: true}
     - {title: "第八节 优先股相关情况", level: 1, required: true}
     - {title: "第九节 债券相关情况", level: 1, required: true}
     - {title: "第十节 财务报告", level: 1, required: true}
   optional_sections:
     - {title: "第一节 重要提示", level: 1, required: false}
   ```

3. 验证 schema：对 100 份该年报告，检查章节覆盖率

**产出**：`schema/{year}.yaml`（9 个文件，2018-2026）

**门禁**：每年 schema ≥ 8 个 required_sections + 100 份验证覆盖率 ≥ 90%

### Phase 4: 源 HTML 结构化解析器（5-7 天）

**目的**：从源 HTML 提取真实文档结构，不从 MD 猜。

**步骤**：

#### 4.1 原型（10 份，做法 H）

1. 从 Gold set 选 10 份（覆盖不同难度）
2. 实现解析器模块 `annual_semi_extraction/parser/html_structure.py`：
   ```python
   def parse_html_structure(html_bytes: bytes, source_key: str) -> StructureTree:
       """从源 HTML 提取结构树。
       
       Returns:
           StructureTree with nodes: heading hierarchy + table positions + paragraph spans
           Each node carries provenance: source_key, extraction_method, resolution_state
       """
       tree = lxml.html.fromstring(html_bytes)
       headings = tree.xpath('//h1|//h2|//h3|//h4')
       tables = tree.xpath('//table')
       # ... 构建结构树
   ```

3. 对每份 HTML 的结构树，用 §2 schema 做匹配（做法 G）：
   - `EXPECTED`：标题匹配 schema 中的 required_section
   - `UNEXPECTED`：标题不在 schema 中（如"小计"、"同比增减金额"）
   - `MISSING`：schema 要求但文档中没有

4. 手工验证 10 份的产出：标题树是否正确、表格位置是否准确、schema 匹配是否合理

**门禁**：10 份手工验证通过 + E1 通过率 ≥ 99%

#### 4.2 扩展（100 份）

1. 扩展到 Gold set 的全部 200 份（sina 源）
2. 自动化 E1 验证：frame_text vs 源 HTML stripped text
3. 自动化 E2 验证：schema 覆盖率

**门禁**：E1 ≥ 99.9% + E2 ≥ 95%

#### 4.3 降级路径（MD-only 文件）

对源 HTML 不可得的文件（cninfo PDF 缺失的 ~65 份），实现降级解析器：
- 从 MD 正则提取标题树（当前 V2 方案）
- `resolution_state` 标记为 `DEGRADED_FROM_MD`
- `provenance.extraction_method = "md_regex_degraded"`

### Phase 5: 句子级分割 + 语义 merging（3-5 天）

**目的**：在结构树（Phase 4 产出）的叶子节点内做句子级分割。

**步骤**：
1. 实现 `annual_semi_extraction/segmenter/sentence_chunker.py`：
   ```python
   def chunk_semantic_unit(su_text: str, target_size: int = 600) -> list[Chunk]:
       """句子级分割 + 语义相似度 merging。
       
       1. spacy 句子边界检测
       2. sentence-transformers 计算相邻句子相似度
       3. 相似度 > θ 合并，否则切分
       4. 累积到 target_size 产出 chunk
       """
   ```

2. 在 Gold set 上评估 Recall@10（E3）

**门禁**：Gold set Recall@10 ≥ 0.85

### Phase 6a: 表格独立管线（3-5 天，可与 6b 并行）

**步骤**：
1. 从 Phase 4 的结构树提取所有 `<table>` 节点
2. 实现 `annual_semi_extraction/table/extractor.py`：
   - HTML 表格 → `pandas.DataFrame`
   - PDF 表格（如有）→ `camelot` + `pandas.DataFrame`
3. LLM 生成表格语义摘要
4. 表格摘要单独 embedding 到 Qdrant

**门禁**：50 张关键表格 cell-level 准确率 ≥ 95%（E4）

### Phase 6b: 引用解析（2-3 天，可与 6a 并行）

**步骤**：
1. 正则提取引用模式：`附注[一二三四五六七八九十百]+`、`第.节`、`参见.{0,20}报告`
2. 在结构树中查找目标节点（先按标题匹配，再用 LLM 语义确认）
3. 存入 PostgreSQL `citation_edge` 表

**门禁**：引用覆盖率 ≥ 80%（E5）

### Phase 7: 多粒度索引（2-3 天）

**步骤**：
1. Section 级：每个一级章节的 LLM 摘要 embedding
2. Frame 级：每个 SU 的 chunk embedding（Phase 5 产出）
3. Proposition 级：LLM 从 chunk 中抽取的原子陈述句 embedding
4. Qdrant 三个 collection 分层

**门禁**：多粒度 Recall@10 ≥ 单粒度 + 10%

### Phase 8: Hash 锚 + 幂等复现（1-2 天）

**步骤**：
1. 每个特征矩阵产出绑定四元 hash（R''7）
2. 随机抽 1% 重跑
3. 比较 frame_id 序列 + source_hash 序列

**门禁**：diff = 0（E6）

### Phase 9: 全量放行（7-14 天）

1. 1000 份规模化验证（性能 + 稳定性）
2. 全量 72K 放行
3. 最终 E1-E6 全量评估报告

---

## 6. 用外部标准重写的执行需求

### R'''0 — 前置诊断（绑定 E1）

**需求**：在投入任何实现之前，先用 100 份样本量化 HTML→MD 的结构丢失量。

**验收**：诊断报告 `deliverables/diag-01-structure-loss.md` 给出 `title_diff_rate` 均值，且结论明确（"值得做 R''1" 或 "不值得"）。

### R'''1 — Gold set 优先（绑定 E3）

**需求**：Gold set 是所有检索质量验证的唯一裁判，必须最先构建。

**验收**：200 份 × 10 查询 = 2000 配对 + Cohen's κ ≥ 0.7 + 对抗性案例 ≥ 20 份。

### R'''2 — Schema-guided 解析（绑定 E2）

**需求**：从 §2 号准则构建 top-down schema，用 schema 过滤非结构标题（解决表格误升格）。

**验收**：2018-2026 各年 schema + 100 份验证覆盖率 ≥ 90%。

### R'''3 — 增量验证环（绑定 E1-E6）

**需求**：10 → 100 → 1000 → 全量，每个阶段有硬门禁，不带着已知缺陷往上跑。

**验收**：每个阶段的门禁报告落盘 `deliverables/gate-{phase}-{scale}.md`。

### R'''4 — Provenance chain（绑定 E1）

**需求**：每个 frame 携带完整溯源链（md_source_hash + source_html_key + extraction_method + resolution_state + schema_match）。

**验收**：任意抽 100 个 frame，provenance chain 完整率 = 100%。

### R'''5 — 对抗性测试（绑定 E3）

**需求**：Gold set 必须包含 ≥ 20 份最难案例（标题混乱/表格密集/结构缺失），不是随机抽样。

**验收**：对抗性子集的 Recall@10 ≥ 0.70（比全量 0.85 宽松，但必须可测量）。

### R'''6 — 可推迟性显式标注（绑定全部）

**需求**：每个推迟项必须有明确的激活条件和触发时机，不允许"以后再说"。

**验收**：`deliverables/deferred-items.md` 列出所有推迟项 + 激活条件。

### R'''7 — 失控防御（绑定全部）

**需求**：以 spec-driven + 外部锚 gate 防止 agent 驱动的失控。

**规则**：
1. 每条 R''' 绑定至少 1 个 E 标准
2. E 标准不通过 = 该 R''' 不通过
3. 禁止在没有 gold set 的情况下声称"质量提升"
4. 禁止在没有 E1 验证的情况下声称"源保真"
5. 每个 Phase 的门禁报告必须落盘

---

## 7. 时间估算

| Phase | 预估工时 | 关键依赖 | 可并行 |
|-------|---------|---------|--------|
| Phase 1: 结构丢失诊断 | 1-2 天 | 无 | — |
| Phase 2: Gold set | 3-5 天 | 无 | ∥ Phase 3 |
| Phase 3: §2 schema | 2-3 天 | 无 | ∥ Phase 2 |
| Phase 4: HTML 解析器 | 5-7 天 | Phase 1+2+3 | — |
| Phase 5: 句子级分割 | 3-5 天 | Phase 4 | — |
| Phase 6a: 表格管线 | 3-5 天 | Phase 4 | ∥ Phase 6b |
| Phase 6b: 引用解析 | 2-3 天 | Phase 4 | ∥ Phase 6a |
| Phase 7: 多粒度索引 | 2-3 天 | Phase 5 | ∥ Phase 8 |
| Phase 8: Hash 锚 | 1-2 天 | Phase 5 | ∥ Phase 7 |
| Phase 9: 全量放行 | 7-14 天 | Phase 4-8 | — |
| **总计** | **29-49 天** | | |

关键路径：Phase 1 → 4 → 5 → 7 → 9 = 18-31 天

---

## 8. 立即可执行的第一步

**今天可以开始**：
1. Phase 1（结构丢失诊断）——不需要任何前置条件
2. Phase 2（Gold set 抽样设计）——不需要任何前置条件
3. Phase 3（§2 号准则获取）——不需要任何前置条件

这三个可以并行启动。

---

**END OF DOCUMENT**
