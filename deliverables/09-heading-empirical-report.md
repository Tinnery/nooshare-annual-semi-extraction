# 一级标题积累法：全量实证报告与需求重写

> Date: 2026-11-13 · **Status: 分析归档 / 条件性方案，当前不启动（Authority: 无）**
> ⚠️ **见 `10-heading-necessity-analysis.md`**：本报告的 U-H1 v3 需求重写**暂不落地**——审查结论是当前不需要一级标题识别能力。
> ⚠️ **见 `11-heading-morphology-correction.md`：本报告多条实证结论已被修正推翻**。误识别（标题+正文粘连、目录页整段吞并、点线/Word 域错误、Wingdings 复选框）污染了统计分母。修正后：`fp_canonical` 未见估计 **1,021 → 383**、top1 占比 24.3% → 52.7%、Simpson 8.18 → 2.95（§二 结果 4 的「未饱和」结论强度须下修）；§三 第 3 条「同 MD 双路径不成立」**被推翻**（实际 744 份可测）。引用本报告数字前必须先看 11 §四。
> 唯一需求权威仍为 `01-requirement.md`（v2）
> 关联：`06-heading-pattern-accumulation-proposal.md`（v2 提案）、`07-gate-decision-sheet.md`（裁决留痕）、`08-heading-codebook.md`（codebook）
> 数据：`data/heading_corpus.jsonl`（12,016 份）、`data/heading_analysis.json`、`data/discriminant_pairs.json`
> 脚本：`scripts/heading_corpus.py`、`scripts/heading_analysis.py`、`scripts/fetch_discriminant_pairs.py`（零新增依赖）

---

## 一、做了什么（不是文档，是实测）

| 步骤 | 产物 | 规模 |
|---|---|---|
| Layer-0 无判据提取（保留 byte offset + verbatim） | `heading_corpus.jsonl` | 12,016 份 MD，0 跳过 |
| verbatim 字节回放校验 | — | 1,926 条，**0 失败** |
| 测量学分析（单位对比/伪重复/Chao1/饱和/消融/反例/分层） | `heading_analysis.json` | 12,016 份 |
| 上游 canonical 覆盖缺口检验 | — | 80 份 smoke，1,119 个 H1 |
| 降级链判别对构造与实测 | `discriminant_pairs.json` + 60 份 winner MD | 60 组 |
| RustFS 键空间核实 | — | 逐对象 head/list |
| DB 元数据关联 | — | 36,970 条 |

**关键**：Layer-0 刻意**不判"什么是一级标题"**，先把原始形态记下来，再由频次反推 codebook。任何预置判据都会污染归纳。

---

## 二、八条实证结果

1. **原始字节证伪了「MD 内目录页/正文双现」**。`000001_2021_2.md` 前 45 行全是 `#`（H1）退化：公司名、`2021年半年度报告`、`重要提示`、`目  录`、`备查文件目录`、`释  义` 各自独立成 H1；目录页**没有**点线标题列表。真正的一级章节是 `# 第一章  公司简介` … `# 第十章  财务报告`（用「章」、两个空格）。06 v1 的 U-H1.2 假设不成立。

2. **分析单位决定结论**。同一语料：`fp_h1`=11,702 种 / `fp_numbered`=1,252 种 / `fp_canonical`=640 种；Chao1 未见估计 1,229,080 / 5,022 / 1,021。`fp_h1` 因公司名与年份近乎无限而给出荒谬上界 → **原始字符串不能作统计单位**。

3. **伪重复极严重**：12,016 份报告的 **Simpson 有效类型数只有 8.18**；top1 组合占 24.27%；且缓存语料 **100% 来自单一 `backup_published|backup_l0` 族**。这意味着：① 频次排名被模板族主导；② **这份缓存不是分层样本，不能外推到全 36,970 份语料**。任何置信界必须按有效样本量重算。

4. **未饱和，且饱和曲线未平**。canonical 单位 `S_obs=640, f1=384, f2=71, Chao1=1661.33`，估计还有 **≈1,021 种**未见组合；累积曲线 11,015 份→557 种、12,016 份→640 种（边际 +83）。**「积累到饱和」在当前语料上不成立**，必须换停止判据。

5. **上游「无需补 357 条」的裁决有条件成立**。canonical 变体实测 57 个 / 15 类，H1 命中率 78.4%；未命中的 21.6% 中 `目录`(69)、年份报告名(63)、公司名、`审计报告`(8) 占绝大多数——**是扉页噪声而非结构标题**。故在「结构标题」范围内上游裁决成立，但**必须叠加 codebook §1.1 的 C 排除规则**；单靠 canonical 映射不足以判 L1。

6. **真实变体不可当噪声丢弃**：`环境和社会责任` 6,089 次 vs `环境与社会责任` 4,553 次；`重要提示、目录和释义` 4,176 次 vs `释义` 3,682 次。二者都是合法高频形态，模糊匹配阈值无法替代显式变体表。

7. **误报源以交叉引用为主**：10,650 份（88.6%）正文含「第X章/节」引用；编号不连续 2,137 份（17.8%）；核心节缺失 1,247 份（10.4%）；无编号标题 331 份；纯文本无 H1 174 份。另有 `五、合并财务报表主要项目注释(续)`（239 次）等**财报附注被误升格为 H1** 的实证反例。

8. **结构异常层必须整体隔离**。60 份降级胜者（`backup_l1/l2/l3`）的 `n_h1` 均值 **76.5** vs 正常 **16.7**（4.6 倍），32 份编号标题达 20 个（正常 10），一份 `n_h1=505`，5 份 `n_h1=0`，18 种组合中 4 种在正常语料中从未出现。**这些必须单列 `EXTRACTION_FAILURE`，绝不可算 `NOT_DISCLOSED`**。

---

## 三、被实证证伪的三条主张（含我自己四段式里的）

| # | 主张 | 证伪证据 | 修正 |
|---|---|---|---|
| 1 | 「交付表 `candidate_count>=2` 天然提供同 slot 多 provider 判别对」 | `candidate_count` 实为 27–88 的**候选公告条目数**；`verify_result` 的 113,524 条 pass **100% 来自 `backup_published` 单一 source**；每 slot 仅一条 MD | 判别对应取「降级链：fail 的 published MD vs 胜者 MD」 |
| 2 | 「降级链判别对可从 RustFS 构造」 | 60 组 fail 侧 **60/60 返回 404**；`published/000065/` 有 33 个对象但无 `000065_2022_4.md`；`verify_result` 留有 60 条指向已消失对象的记录 | **判别对在授权数据源内不可构造**；改为把 60 份胜者作「结构异常层」分层刻画，并把 60 条悬空引用登记为数据完整性缺陷 |
| 3 | 「同一 MD 内目录页 vs 正文可作双路径」 | 见结果 1；目录页被压成单个 `# 目  录` H1 | E4 双路径需改用「canonical 签名 vs 编号型标题序列」两条**同源于 MD 但独立构造**的路径，或走 Human Gate 申请上游 `dual_channel` 产物 |

> 这三条都是**用原始字节与 DB 事实推翻的书面推理**。这正是"更深"与"更大"的分界：不靠更多文档，靠可证伪的证据。

---

## 四、重写后的需求（U-H1 v3，用上述标准）

沿用 R'0-R'9 / E1-E6 / M1-M3，**不新增代际、不新增 E 编号、不新增依赖**（01 §七）。相对 06 v2 的**根变化**：第一条不再是"保真"，而是先固定测量学对象。

| # | 需求 | 绑定锚 | 可机器校验产物 |
|---|---|---|---|
| **U-H1.A** | **定义 codebook 与分析单位并版本化**（`08` §一/§二）；pilot 200 份双盲标注，α<0.8 改 codebook 不改模型 | M1 / 04 §2-F | `unit_scheme=heading-unit-v1`、gold set（与积累集隔离）、α 报告 |
| **U-H1.B** | **模板族去冗余**：按 `fp_canonical` × `winner_source` × `selection_rule` 聚类，报告 **Simpson 有效样本量**及分层构成；单一族占比过高时不得外推 | E1 / 05 C2 | 有效样本量、族分布、外推禁告 |
| **U-H1.C** | **两条独立路径**（非 HTML）：canonical 签名路径 vs 编号型标题序列路径；分歧落 evidence；`DIVERGENT_THRESHOLD=0.3` | E4 / M2 | 分歧清单 + verbatim span |
| **U-H1.D** | **判别对改为分层对比**：结构异常层（60 份降级胜者）vs 正常层；同 (code, period) 相邻年份最小对立对。**不得宣称同 slot 多 provider 判别对** | E1 / E5 | `discriminant_pairs.json` + 层间差异报告 |
| **U-H1.E** | **停止判据 = S-3 单调收敛 + Chao1 上界**，显式报告未饱和；禁止以"连续 k 份无新类型"或全量合规率收尾 | 01 §五 / E5 | `monotonic_check`、Chao1 + bootstrap CI、饱和曲线 |
| **U-H1.F** | **积累循环**：每轮记录命中集合 sha256 + 边际新增覆盖 + **leave-one-out 贡献度**；命中集合移出 candidate pool 但**保留在 replay set** 做零回归 | M3 | 回放 diff=0、消融表、残差集（本次 1,213 份 / 10.1%） |
| **U-H1.G** | **反例库**：每个 pattern 绑定 near-miss（最小编辑距离）；财报附注/交叉引用/公司名/年份名作固定负例 | R'1⑥ / M2 | near-miss 表 + 固定负例集 |
| **U-H1.H** | **三态举证责任**：未通过 L1 检测一律 `EXTRACTION_FAILURE`；结构异常层 60 份整体单列；`NOT_DISCLOSED` 须人工复核原文 | E1 / 05 C2 | 三态分层矩阵 |
| **U-H1.I** | **裁判四层分离**（`08` §四）；AGENT 仅在 L-仲裁层，不得产出事实 | M1/M2/E4 | 分层判定日志 |
| **U-H1.J** | **README 级声明**：本次 12,016 份缓存**不是分层样本**（100% 单族），所有结论只对该缓存有效；扩展到 36,970 份须重新分层抽样 | 01 §五.2 | 范围声明 + 分层抽样计划 |

---

## 五、外部客观标准（不变，但用实证校准了用法）

| 标准 | 本次实证中的用法 |
|---|---|
| E1（法规文号 + 施行日 + 原文 sha256） | 定义应然组合；**与频次完全解耦** |
| M2 verbatim 回放 | `md_bytes[start:end].decode() == verbatim`，1,926/1,926 通过，进 CI |
| E4 双路径收敛 | 改用 canonical vs 编号型两条独立构造路径（HTML 路径不可得） |
| Chao1 + bootstrap | 给「未见形态」上界，证明**未饱和** |
| S-3 `monotonic_check` | 收敛证据（`proof-2018-final.json` M0=2030→M1=0） |
| Krippendorff's α | **仅标注过程质控**，不作正确性标准（01 §2.3 / 04 §2-F） |
| 05 C2/C3/C4 | gate 状态、单位/判定程序版本化、变更重跑 |

---

## 六、遗留（需 Human 动作，Agent 不自行处理）

1. **60 条悬空 `verify_result` 记录**指向 RustFS 已不存在的对象——属上游数据完整性缺陷；本 repo 不修改上游，仅登记。
2. **缓存非分层样本**：12,016/36,970，且 100% 单族。要给出覆盖全语料的结论，须按 `year × period × source` 重新分层抽样（上游 F-013，每层 ~5%）。
3. **上游 `dual_channel` 产物**（`dual_channel_report.json` / `divergent.jsonl`）本地无落盘；若要恢复 E4 的 HTML/PDF 双通道，需确认是否在 pro 主机 / RustFS，并按 01 §四走变更流程。
4. **`chapter_extractor.py` 手敲 `CHAPTER_KEYWORDS` + 清洗销毁 verbatim span** 仍未修复（违 M2 / R'1②⑥），不得进入 U-H1 主链路。
5. **06 v2 的 U-H1.2 / U-H1.3 / U-H1.7** 已被本报告结果 1、4 与 §三 证伪/修正，合入 01 前须按 U-H1 v3 更新（④A 裁定仍是暂不合入）。
6. `e1_validation_test.json` / `e1_validation_full.log` 为 `BLOCKED_ON_GATE` 期间的作废产物，未删除。

---

## 七、本轮实际交付文件

| 文件 | 内容 |
|---|---|
| `deliverables/08-heading-codebook.md` | codebook、分析单位、标注流程、裁判四层、失败分类学 |
| `deliverables/09-heading-empirical-report.md`（本文件） | 实证结果、证伪记录、U-H1 v3 需求重写 |
| `scripts/heading_corpus.py` | Layer-0 无判据提取（byte offset + verbatim 可回放） |
| `scripts/heading_analysis.py` | 测量学分析（10 类统计，零新增依赖） |
| `scripts/fetch_discriminant_pairs.py` | 降级链判别对构造 |
| `data/heading_corpus.jsonl` | 12,016 份候选语料 |
| `data/heading_analysis.json` | 分析结果 |
| `data/discriminant_pairs.json` | 60 组判别对及其 404 证据 |

**未改**：`01-requirement.md`、任何注册表 sha、AGENTS.md、README、pyproject（零新增依赖）。`pytest -q` 仍为 35 passed。

---

**END OF DOCUMENT**
