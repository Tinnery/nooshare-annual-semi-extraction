# 一级标题误识别的修正：形态建模而非提高识别率

> Date: 2026-11-13 · **Status: 分析归档（Authority: 无）** · 唯一需求权威仍为 `01-requirement.md`（v2）
> 触发：用户指出 `data/heading_analysis.json` 中有明显的一级标题误识别
> 实证：`data/heading_recompute.json`、`data/heading_corpus_clean.jsonl`、`data/heading_corpus.jsonl`
> 脚本：`scripts/heading_morphology.py`、`scripts/recompute_clean.py`、`scripts/verify_morph_spans.py`

---

## 〇、修正的层次（先把话说清）

**不是"提高一级标题识别率"。** `10-heading-necessity-analysis.md` 已论证本 repo 不需要该能力；提高识别率会在错误前提上继续投入。

真正的修正是三件事：

1. 把 **MD 转换链路造成的系统性损伤**显式建模，使其**不进入统计分母**（此前 08/09 的每个数字都被污染了）；
2. 给 `EXTRACTION_FAILURE` 提供可诊断的形态分层（10 §六保留的最小能力之一）；
3. 给「字数」列 / `semantic_path` 提供可回指的边界（之另一）。

**铁律**：verbatim 一字不改；所有修正都是**派生字段**，每个 segment 带可回放偏移；合法名称只来自外部有限集；不做 AGENT 正确性判断；不清洗覆盖原文。

---

## 一、误识别的类型学（全部有真实字节证据）

| 形态 | 原始 verbatim（截取） | 物理成因 | 污染后果 |
|---|---|---|---|
| **M1 标题+正文粘连** | `# 第一节 重要提示、目录和释义公司董事会、监事会及…法律责任。` | Word 段落合并，标题与正文首段挤进同一行 | 制造 3,539 个伪变体（1179/581/552/340/887） |
| **M2 目录页整段吞并** | `# 第一节 重要提示… ...... 错误！未定义书签。第二节 公司简介… (共 10 节)` | Word 目录域失效，整个 TOC 被压成一行 | 10 个节被压成 1 个 → 直接制造 `ORDINAL_NOT_CONTIGUOUS` / `CORE_SECTION_MISSING` |
| **M3 点线+页码残留** | `# 第五节环境和社会责任 ...... 24第六节重要事项..................` | 目录点线与页码混入正文行，marker 与名称间无空格 | name 吞并后续节与数字 |
| **M4 复选框残留** | `# 第九节 债券相关情况?适用 □不适用` | Wingdings 复选框被映射为 `?`/`□` | conditional 章节名带表单尾巴 |
| **M5 空名称** | `# 第十节` | 标题名称在下一行 | 740 次 name 为空 |
| **M6 非结构升格** | `# 五、合并财务报表主要项目注释(续)` / `# 目录` / `# 2021年年度报告` / `# 审计报告` | 财报附注、扉页、表头被转成 H1 | 24,665 个 distinct H1 文本，多数不是章节 |

**因果自证**：`ORDINAL_NOT_CONTIGUOUS` 在 `2021_P2` 为 **1580/4086 (38.7%)**，`2021_P4` 仅 **399/4017 (9.9%)**；`CORE_SECTION_MISSING` 为 **992 (24.3%)** vs **128 (3.2%)**。半年报问题重得多——这是转换链路缺陷的分布特征，不是"半年报公司普遍不披露章节"。

---

## 二、修正实现

### 2.1 合法名称集（外部有限集，禁止手敲）

`heading_morphology.legal_name_set()` 动态合并：
- `annual_semi_extraction/spec/legal_chapters.json` 全部 5 个版本的 `sections[].name`；
- 上游 `reference/report_patterns.json` 的 `canonical` 全部变体。

共 **59 条**，按长度降序编译为**单一交替正则**（沿用上游 `heading_verify.py` 做法，避免 O(n×m) 扫描）。所有 `clean_names` 必须属于该集合——`verify_morph_spans.py` 强制校验，本次 **自造名称 0**。

### 2.2 确定性切分（优先级有序，首个命中即定形态）

```
TOC_ROW      一行含 >=2 个 第X章/节 marker，或含「错误！未定义书签。」
TOC_TAIL     点线 [\.…·]{2,} 残留 / 尾部页码
CHECKBOX     [□■☑☐?]适用 / 适用□ 等表单残留
EMPTY_NAME   纯 marker（名称在下一行）
NONSTRUCTURAL 目录标题变体 / 年份报告名 / 公司名 / 审计报告 / 财报附注续行
GLUED_BODY   命中合法名后仍有含句末标点的正文后缀
CLEAN        干净命中合法名
UNRESOLVED   其余 → 进 evidence，不进统计分母（M2 / 08 §1.3）
```

`split_markers()` 按**行内所有 marker** 切成片段 → 每段剥离点线/Word 域错误/复选框/页码 → 用合法名做最长前缀匹配 → 得到 `name` 与 `body_suffix`。TOC 行切出的节名单独存 `toc_sections`，**不并入正文签名**（避免目录页自证）。

> 与 `chapter_extractor.py` 的根本差别：旧代码用 `re.sub` **清洗掉**页码与空格，verbatim 被销毁（违 M2）；本修正保留原字节，只加派生标注。

### 2.3 自检（5 个已知误识别样本）

| 输入 | 输出 |
|---|---|
| `第一节 重要提示…公司董事会…法律责任。` | `GLUED_BODY` → `重要提示、目录和释义`，正文后缀分离 |
| `第五节环境和社会责任 ...... 24第六节重要事项......` | `TOC_ROW` → 2 段：`环境和社会责任` / `重要事项` |
| `第九节 债券相关情况?适用 □不适用` | `CHECKBOX` → `债券相关情况` |
| 10 节 + `错误！未定义书签。` | `TOC_ROW` → 按 marker 逐节切出 |
| `第十节 财务报告` | `CLEAN` → `财务报告` |

### 2.4 M2 回放校验（`verify_morph_spans.py`）

```
报告 12,016 · H1 200,884 · segment 204,021
span 越界 0 · 自造名称 0 · verbatim/偏移不一致 0
=> PASS — 修正为纯派生，M2 未被破坏
```

---

## 三、修正前后对比（12,016 份全量）

| 指标 | 修正前 | 修正后 | 变化 |
|---|---|---|---|
| `fp_numbered` 唯一组合 | 1,252 | **510** | −59.3% |
| `fp_numbered` Chao1 / 未见 | 6,274 / 5,022 | **1,351 / 841** | −83.3% |
| `fp_canonical` 唯一组合 | 640 | **339** | −47.0% |
| `fp_canonical` Chao1 / **未见** | 1,661 / **1,021** | **722 / 383** | **−62.5%** |
| `fp_canonical` top1 占比 | 24.27% | **52.68%** | ×2.17 |
| Simpson 有效类型数 | 8.18 | **2.95** | −63.9% |
| `CORE_SECTION_MISSING` | 1,428 | **1,778** | ↑（口径变严，见 §四） |

形态分布（200,884 个 H1）：`CLEAN 122,241` / `NONSTRUCTURAL 36,706` / `UNRESOLVED 35,134` / `GLUED_BODY 2,952` / `TOC_TAIL 2,097` / `EMPTY_NAME 740` / `TOC_ROW 664` / `CHECKBOX 350`。

剩余 35,134 个 `UNRESOLVED` 主要是**正文段落被误升格为 H1**（如「所有董事均已出席了审议本报告的董事会会议。」「项目列示」）。按 08 §1.3 规定，它们记 `UNRESOLVED` 进 evidence、**不进统计分母**，不应继续扩规则去"识别"它们。

---

## 四、哪些结论被推翻 / 未被推翻（诚实登记）

### 4.1 被推翻

| 09 原结论 | 修正后 | 判定 |
|---|---|---|
| 「canonical 组合**未饱和**，未见 ≈1,021 种，积累法没有停止点」 | 未见降至 **383**（−62.5%），top1 占比翻倍至 52.7% | **主要是误识别造成的假象**；仍未完全饱和，但量级与结论强度须下修 |
| 「同一 MD 内目录页/正文双路径**不成立**（目录页被压成单个 H1）」 | 该判断只对 `000001_2021_2` 成立；`000007_2021_2`、`000011_2021_2` 等**确有完整目录列表**，只是被压成一行 | **被推翻**：双路径一直存在，是我把 TOC 行当成了单个损坏标题 |
| 「判别对 0 组，E4 双路径需 Human Gate 申请上游产物」 | 同 MD 双路径**技术可测 744 份**（一致 516 / 分歧 228） | 需修正为「可测但有限」，见 §4.3 |

### 4.2 未被推翻，反而加强

**`10` 的「不需要建一级标题识别能力」结论成立且更强**：
- 误识别的根因是**转换链路的字节损伤**（段落合并、Word 域失效、Wingdings 映射），不是识别算法不够好；再好的识别器也救不回已粘连的字节。
- 修正只需 **59 条外部有限集 + 确定性形态规则**，不需要 codebook、pattern 库、gold set、α 标注或 AGENT 判定。
- 修正后有效类型数 **8.18 → 2.95**，语料比原先判断更单一，重型识别系统更无必要。
- 上游 `HARD_CHECKS` 不含标题判定、`72,704 份 gate_fail=false` 的事实不变。

### 4.3 双路径的新局限（不能因为"能测"就宣称"能用"）

744 份可测（占 6.2%），但 228 份分歧中**几乎全是 `仅正文` 有、`仅TOC` 无**：`documents` 12 次、`governance` 11、`shares` 10、`esg`/`financial`/`matters` 各 9；`仅TOC` 只有 `notice` 3 次。即**不是目录与正文不一致，而是 TOC 侧切分不完整**（目录页跨多行时只捕到前几节）。

故：516 份"一致"可作交叉背书；228 份"分歧"**不能直接判 DIVERGENT**，须先把 TOC 切分做全或显式标注 `toc_partial`。E4 若要可靠收敛判据，仍需 Human Gate 确认上游 `dual_channel` 产物。

### 4.4 口径变化说明

`CORE_SECTION_MISSING` 从 1,428 **上升**到 1,778，不是修正变差，而是口径变严：修正前上游 `extract_heading_signature()` 会把**目录页声明的章节**算作正文证据（自证）；修正后 TOC 节名单独存放、不并入正文签名。按 `10` 的结论，这些数字无论如何都**不能直接用来判 `NOT_DISCLOSED`**——标题判缺 ≠ 真缺。

---

## 五、给 `chapter_extractor.py` / `e1_judge.py` 的处置建议（未修改）

| 文件 | 问题 | 建议 |
|---|---|---|
| `chapter_extractor.py:50` | `re.sub` 清洗页码 + `strip()` 拼字符串，销毁 verbatim | 不进 U-H1 主链路；如需保留，改为输出派生字段并保留原 span |
| `chapter_extractor.py:21` `CHAPTER_KEYWORDS` | 手敲关键词表，与 `scripts/extract_chapter_pattern.py:26` 另一份不一致 | 删除；统一改用 `heading_morphology.legal_name_set()` 的外部有限集 |
| `e1_judge.py` `_matches()` / `_matches_split()` | 字符重叠 >0.7、关键词覆盖 ≥50% 等无外部身份的模糊阈值 | 按 `10` §六：E1 主路径改为 `reg_version → legal_chapters` + verbatim 内容证据 + 三态举证；模糊匹配不进判定链 |

本次**未改动**以上三个文件、`01-requirement.md`、任何注册表 sha、AGENTS.md、README、pyproject（零新增依赖）。`pytest -q` 仍 35 passed。

---

## 六、新增文件

| 文件 | 用途 |
|---|---|
| `scripts/heading_morphology.py` | 形态分类 + 确定性切分（外部有限集驱动） |
| `scripts/recompute_clean.py` | 全量重算 + 前后对比 + 双路径统计 |
| `scripts/verify_morph_spans.py` | M2 回放不变量校验 |
| `data/heading_corpus_clean.jsonl` | 12,016 份形态分类结果 |
| `data/heading_recompute.json` | 修正前后对比、双路径样例 |
| 本文件 | 修正方法与结论变更登记 |

---

**END OF DOCUMENT**
