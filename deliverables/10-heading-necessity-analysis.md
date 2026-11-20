# 到底需不需要识别一级标题：前提审查

> Date: 2026-11-13 · **Status: 分析结论（Authority: 无）** · 唯一需求权威仍为 `01-requirement.md`（v2）
> 关联：`08-heading-codebook.md`、`09-heading-empirical-report.md`（本文件**推翻其执行前提**，但不删除其证据价值）
> 实证：`data/chapter_necessity.json`（1,200 份抽样 × 5 节 = 6,000 节对）、上游 `HARD_CHECKS` / `verify_l0.py` / `proof-2018-final.json`
> ✅ **本文件结论经 `11-heading-morphology-correction.md` 复核后仍然成立且被加强**：误识别的根因是转换链路的字节损伤（段落合并 / Word 域失效 / Wingdings 映射），不是识别算法不足；修正仅需 59 条外部有限集 + 确定性形态规则，无需 codebook / pattern 库 / gold set / AGENT；修正后有效类型数进一步降至 2.95。本文件 §四 引用的 09 数字为修正前口径，仅用于说明「标题判缺 ≠ 真缺」的方向性，具体量级以 11 §三 为准。

---

## 结论（先给答案）

**不需要把「一级标题识别」建成一个独立能力或判定前提。**
需要保留的不是"识别"，而是两个更小的东西：**章节边界定位**（给"字数"列与 `semantic_path`）和 **结构退化诊断**（给 `EXTRACTION_FAILURE`）。

更精确的重新定位：

| 原定位（06/08/09 的隐含前提） | 审查后定位 |
|---|---|
| 一级标题识别 → E1 完备性判定的**输入** | 一级标题签名 → **advisory 观测 / 结构指纹 / 抽取失败诊断信号**（与上游一致） |
| 需建 codebook、pattern 库、gold set、α 标注、Chao1 停止判据 | **当前不启动**，除非 §五 的触发条件之一成立 |
| 命中不了标题 = 章节未披露 | 命中不了标题 = **工程未抽取成功**，须先归 `EXTRACTION_FAILURE` |

---

## 一、先消歧：「一级目录」指什么

| 所指 | 实证 | 结论 |
|---|---|---|
| **TOC 目录页**（带点线页码的章节列表） | `000001_2021_2.md` 里目录页被压成单个 `# 目  录` H1，**没有标题列表**；12,016 份中 `目录` 作为 H1 出现 10,502 次，几乎都是这个形态 | 数据里**不存在**可用的目录结构 → 既无法识别，也无需识别 |
| **一级标题 / 章节结构**（`# 第X章 …`） | 存在且高频（编号标题名 Top12 与法定节名高度吻合） | 见下述分析 |

下文按第二种理解。

---

## 二、E1 到底要判什么（规格原文）

`01-requirement.md` §2.3：

> E1 判定函数 = `reg_version(…) → 法定章节集；算 missing/extra/order；三态分别计数`
> 通过条件 = **`NOT_DISCLOSED` 打监管 flag；`EXTRACTION_FAILURE` 判工程 fail；`NOT_APPLICABLE` 不计缺失**

关键点：

1. **验收对象是三态缺失分类**，不是"标题字符串是否匹配"。法规要求的是「第X节应披露 XXX 内容」，不是「必须出现某个标题字样」。
2. `extra` / `order` 被要求"算"，但 **pass_condition 里没有给它们任何判定语义或处置**。为它们建重型识别系统属无验收依据的扩能力。
3. R'1 v1 要求矩阵含「命中/缺失/**字数**」——"字数"需要章节边界，但**边界定位 ≠ 一级标题识别**（编号型 marker 的 byte offset 即可，无需 codebook / pattern 库 / gold set）。
4. `05-consumer-contract.md` §一：**运行时消费者 0**；C5.3「消费者出现前不得为将来可能被用而扩列、扩索引、扩粒度」；C5.4「读者缺失即停机，视为过度实现，按铁律 4 回收」。

---

## 三、上游已经用实践回答了这个问题（最有力的一条）

上游 `nooshare-annual-semi` 已完成 **72,704 份 MD 的完备性证明**（`proof-2018-final.json`: `gate_fail=false`、`terminal_state=complete`、`monotonic_check=pass`）。其判定配置：

| 证据 | 原文 / 事实 |
|---|---|
| `annual_semi/tasks/verify.py:24-27` | `HARD_CHECKS = ("too_short","stub_content","year_mismatch","truncated","content_sha256_unique","terminal_sections","time_consistency")` —— **七项无一依赖标题** |
| `annual_semi/completeness/verify_l0.py:160` | 「结构指纹（advisory）… 仅用于 `fingerprint_collision` advisory 标注与标准 #5 多源交叉，**绝不产生 fail**」 |
| `deliverables/02-technical-solution.md:400` | `excerpt` = 既有 `check_heading_signature().verdict`（**advisory**） |
| `deliverables/01-requirements.md:267` | 「`terminal_sections` 是**子串匹配，不依赖标题提取**，因此纯文本 MD 也需通过」 |
| `verify_result.checks` 实测 | 5,000 样本 9 个 key，**无 `heading_signature`**；25,847 条 fail 全部来自 `terminal_sections` |
| `extract_heading_signature()` 真实用途 | 结构指纹 `fingerprint`、`dual_channel` 的 Jaccard 输入、降级链——**从不作完备性硬判定** |

> 即：上游在**没有一级标题硬判定**的情况下完成了完备性证明，并刻意把标题签名降级为 advisory。理由是明确的：纯文本 / 结构退化 MD 也必须能通过验证。

本 repo 若再建一套高精度一级标题识别作为 E1 前提，是**重复实现（铁律 4）且比上游更严格因而更脆弱**。

---

## 四、本 repo 数据的反证

### 4.1 标题法会把工程缺陷误报成监管违规

`scripts/chapter_necessity_test.py`，1,200 份抽样 × 5 个 core section = 6,000 节对：

| 混淆 | 数量 | 含义 |
|---|---|---|
| A1_B1 | 4,289 | 标题有、正文锚点有 |
| A1_B0 | 1,412 | 标题有、正文锚点不足（**多为锚点词设计过窄，非标题法虚报**，见下） |
| A0_B0 | 182 | 标题无、正文锚点无 |
| **A0_B1** | **117** | **标题法判缺，但正文非标题行仍有内容锚点** |

**标题法判缺的 299 个节对里，39.1% 正文仍有内容**。这些漏报样本的特征：

- `n_numbered = 0`：32/40
- `n_h1 = 0`：25/40
- 典型案例 `601998_2021_2`：五个 core section 全部被判缺，但该报告 `n_h1=0`，是**纯文本格式**

也就是说，标题法的失效集中在**结构退化报告**——而这类报告在 E1 三态里恰恰应归 `EXTRACTION_FAILURE`。用标题识别做判定前提，会系统性地把「抽取失败」误报为「公司未披露」，正是 01 E1 `failure_taxonomy` 明令禁止的 **"EXTRACTION_FAILURE 伪装成未披露"**。

### 4.2 内容锚点法也不是替代品（诚实标注本检验的局限）

`A1_B0=1,412` 主要源于我的锚点词只用了节名同义词，很多章节正文不重复节名（如「管理层讨论与分析」整节讲业务）。**所以本检验不能推出"改用内容法即可"**，只能推出「标题法判缺 ≠ 真缺」这一条。要可靠判 `NOT_DISCLOSED`，仍需 `reg_version → legal_chapters.json` 定应然 + verbatim 内容证据 + 人工复核举证（08 §四裁判四层）。

### 4.3 成本没有上界

`09` 实证：canonical 组合 `S_obs=640, Chao1=1661.33`，**未见 ≈1,021 种**，饱和曲线在 12,016 份时仍在增长（边际 +83）；有效类型数仅 8.18。一个未饱和、且语料 100% 来自单族缓存的识别系统，其"做完了"没有可判定标准——这本身就不该成为门禁前置。

---

## 五、什么条件下才真的需要

| # | 触发条件 | 需要的到底是什能力 | 当前状态 |
|---|---|---|---|
| A | `chapter_compliance` 的**「字数」列成为硬验收项** | **章节边界定位**（编号 marker 的 byte offset 切分），失败归 `EXTRACTION_FAILURE`；**不需要** codebook/pattern 库 | R'1 v1 有此列，但无消费者、无验收规则 |
| B | 二期 `nooshare-annual-semi-research` 真的消费章节级特征 / `semantic_path` | 同上 + 字段契约 | 消费者 0（05 §一），repo 尚不存在 |
| C | E1 的 `extra` / `order` 被赋予验收语义 | 有序标题序列（仍需先定义"违规"标准） | pass_condition 未定义，当前无语义 |
| D | 要判 `NOT_DISCLOSED` 且要求可反驳证据 | 章节级 **verbatim span 定位**（证据，不是识别） | 走 M2 + 人工复核即可 |

**A–D 均未成立**。按 05 C5.3 / C5.4，在这些条件成立前建重型识别能力属过度实现，应回收。

---

## 六、建议的动作（不改 01，不改注册表）

1. **重新定位**：把一级标题签名明确标为 `advisory`，与上游 `verify_l0.py:160` 对齐；**不得作为 E1 判定输入**。
2. **E1 主路径改为**：`reg_version → legal_chapters.json`（应然）→ MD 全文 verbatim 内容证据（实然）→ 三态举证责任 → 人工复核 `NOT_DISCLOSED`。标题签名只作诊断列。
3. **保留最小边界能力**：编号型 marker 的 byte offset 切分，供「字数」列与 `semantic_path`；结构退化（`n_h1=0` / 无编号）直接归 `EXTRACTION_FAILURE`，不为覆盖它们扩 pattern。
4. **08/09 状态调整**：标记为**分析归档（条件性方案，当前不启动）**。其价值是给出了「为什么不需要」的可证伪证据与成本上界，不是待执行规格。
5. **06 v2 的 U-H1 与 09 的 U-H1 v3 暂不落地**；④A「暂不合入 01」的裁决继续有效，且理由更充分。
6. **登记两条上游数据事实**（本 repo 不修改上游）：60 条指向 RustFS 已消失对象的 `verify_result` 记录；`dual_channel` 产物本地无落盘。

### 触发复评的信号

- 05 契约登记了真实 `consumer_id` 且 `consumes_columns` 含 `chapter_compliance`；
- 或 Human Gate 把「字数」列 / `extra` / `order` 写入 E1 pass_condition；
- 或出现需要章节级 `semantic_path` 的特征需求。

---

## 七、这一轮没有白做

06/07 的裁决、08 的 codebook、09 的 12,016 份实证，共同产出了**否定性知识**：证明了「按频次积累一级标题 pattern」在概念上错位（把格式层当法规层）、在实践上未饱和、在治理上无消费者、在上游已有更轻的等价方案。否定一个前提比在错误前提上继续优化更省时间——这也是「更深」与「更大」的分界。

**新增文件**：`scripts/chapter_necessity_test.py`、`data/chapter_necessity.json`、本文件。
**未改**：01、任何注册表 sha、AGENTS.md、README、pyproject（零新增依赖）。`pytest -q` 仍 35 passed。

---

**END OF DOCUMENT**
