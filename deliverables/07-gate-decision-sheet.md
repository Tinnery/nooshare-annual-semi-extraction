# 四项裁决决策单（决策记录，非规格，无 Authority）

> Date: 2026-11-13 · 对应 `deliverables/06-heading-pattern-accumulation-proposal.md` §六
> **v2：已纳入上游 `C:\dev\nooshare-annual-semi` 交叉知识核对，②③ 的推荐项据此修正。**
> 本文件不是需求文档，不产生 R 代际、不改 01 权威地位。用途：让 4 项裁决可一次性勾选、可留痕。

## 最小回复格式

```
①A  ②A  ③默认  ④A
```
即全部按推荐项放行。**未回复任何一项 = 该项不推进，我不动对应文件。**

## 裁决负担分解（先看这个）

| 项 | 是否真的需要你判断 | 实质 |
|---|---|---|
| ① | **是**，但只是追认/回滚/改判三选一 | 你此前已裁决 `by_period_end`，现在只是把已生效的事实写进 01 |
| ② | **是** | 是否扩大 01 §四 取数契约；交叉核对后推荐项含义已变（见下） |
| ③ | **否** | 参数在上游已冻结，说"默认"= 直接继承，无需你造数字 |
| ④ | 否，推荐"暂缓" | 现在合入会污染唯一权威；且 06 需先做上游资产映射，否则违铁律 4 |

**另一个表述修正**：`pytest -q` 的 14 failed 里，**只有 2 个是规格问题**（`test_spec.py` 的 sha 登记 + `UNRESOLVED` 断言），其余 12 个是上一轮给 `resolve_version()`/`judge()` 加 `report_year` 参数后测试调用没同步（`TypeError: missing 1 required positional argument: 'report_year'`）。后者是纯工程同步，批准 ① 后我直接改，不需要你逐条裁决。

---

## 〇、上游交叉知识核对结果（**这是本轮新增，直接改变 ②③**）

> 依 AGENTS.md 铁律 4「优先复用上游已有能力，禁止重复实现」核对 `C:\dev\nooshare-annual-semi`。下列均为**只读事实**。

| # | 上游资产（路径） | 内容 | 对裁决的影响 |
|---|---|---|---|
| 1 | `reference/report_patterns.json` | **已经是 pattern 库**：15 类 `canonical` 变体映射（完整）+ Top-5 `patterns`（带 `frequency` / `stocks`，如 id=1 freq=15396 stocks=2874）。注释称全量 357 条 verified patterns 覆盖 33,003 份报告 | 用户要的"积累到 pattern 库并记录命中 md 个数"**上游已存在** |
| 2 | `deliverables/02-technical-solution.md` | 明确记载：「`patterns` 只是 Top-5 种子；`extract_heading_signature` 只用 `canonical` 变体映射（完整 15 类），不依赖 `patterns` 数组；**无需补 357 条**」 | **上游已裁决过"不必补全 pattern 库"**；06 提案的"积累到饱和"需重估 |
| 3 | `annual_semi/identify/_funcs/heading_verify.py` | 一级标题签名 = canonical 类别序列；最长变体优先（编译为单一交替正则）；5 个 `_CORE_SECTIONS` 完备性校验；无标题返回 `pass` | L2 语义归一已有实现，且比下游手敲 `CHAPTER_KEYWORDS` 强 |
| 4 | `annual_semi/semantic/_funcs/report_structure.py` | `is_toc()`（`[\.…·]{2,}\s*\d+$` 判目录页）、`is_metadata()`、`is_heading()`、`heading_level()`、`clean_heading_prefix()` | **L1 边界检测已存在**；目录页/正文可区分，无需新建 |
| 5 | `annual_semi/semantic/_funcs/patterns.py` | 标题规范化（全角、异体零 O、中文数字年份 cn→ar 含大写/繁体）、`should_exclude_position_aware()`、stub / 截断检测 | L1 归一化已有实现，直接复用 |
| 6 | `annual_semi/completeness/dual_channel.py` | **HTML 通道 vs PDF 通道 + `jaccard_distance` + `DIVERGENT_THRESHOLD = 0.3`（D-3 冻结）**；分歧不自选胜者、回入 `M_n`；通道不可用则 `SKIPPED` 不抛异常；`dry_run=True` 默认只算不写 | E4「双路径收敛」**上游已实现且有冻结阈值**；06 提案设想的"MD 内目录/正文双路径"属重复实现 |
| 7 | 上游 `deliverables/01-requirements.md` S-3 / F-008 | **单调收敛性**：缺失集 `M0 ⊇ M1 ⊇ … ⊇ Mn`，每轮差集有逐条 receipt，`monotonic_check = pass` | 正是用户说的「命中集合脱离下一轮」，**已是可验证不变量** |
| 8 | 同上 F-012 | **结构指纹**：对每份 MD 算章节标题序列的 SHA-256，`(report_year, period) → 指纹` 唯一性约束，同指纹多槽位 = 数据污染 | 「一级标题组合」的现成表达，可直接当 pattern id |
| 9 | 同上 F-013 / §5 标准 6 / §7.4 | **分层抽样**：`year × period × source`，每层 ~5%（最少 1 个），人工核对 MD 与原始 PDF 章节级一致性；覆盖率 100%、人工 pass ≥95% | **③ 的分层与抽样比例上游已冻结** |
| 10 | 同上 §5 标准 5 | 多源交叉：`candidate_count >= 2` → `multi_source`，`== 1` → `single_source`（只标注、不设阈值 fail） | 双路径可得性的现成代理变量 |
| 11 | `annual_semi/completeness/__init__.py` | `slot_key(code, year, period) = "code_year_period"`；`parse_slot_key()` 严格校验（code 6 位 / year 4 位 / period ∈ {2,4}） | 铁律 4 指定要复用的公共类型；下游 `report_id` 应显式复用 |
| 12 | `deliverables/proof-2018-final.json` | `gate_fail=false`、`terminal_state=complete`、`monotonic_check=pass`、`M_0=2030 → M_1=0 → M_2=0`、`l0_persistence.diff=0` | 完备性证明与单调收敛已通过 |
| 13 | `deliverables/completeness_2021_2024.json` | 2021–2024 窗口：`expected 37,406`、`delivered 36,969`、`unobtainable 437`（全部 `source_403_blocked`）、`gap_outside_terminal=0`、`completeness_rate_pct=98.83`，附 `by_year_period` 八层 | **③ 的残差集 / 分层基线现成可用** |
| 14 | `annual_semi/converter/_funcs/html2md.py` | 头部注释：「All semantic classification is delegated to the semantic Unit」；导入 `is_toc/is_heading/heading_level`；`_merge_numbered_headings()` 处理编号与标题分离 | 转换链路**保留**了目录页判定，标题层级由 semantic unit 判定而非正则猜 |
| 15 | `dual_channel.py:52,108` | `_PDF_ROOT = /backup/bulletin/source/pdf`；`source/html/{code}/{native_id}.html` 键 | 源 HTML/PDF 在**上游生产时**真实存在且被使用；但这是"实然"，不等于下游"可采"（01 §四） |

**可复用能力**：1/3/4/5/6/11/14 的代码与数据 · **只读事实**：2/7/8/9/10/12/13/15 的规格与产物 · **未找到**：`artifacts/` 目录为空，本地**没有** `dual_channel_report.json` / `divergent.jsonl` / `unobtainable.jsonl` / `manifest.sqlite3` 落盘（仅 `deliverables/` 下两个 JSON）。故"直接消费上游双通道结论"在本地不可行，需确认是否在 pro 主机 / RustFS。

---

## ① 是否追认 `by_period_end` 裁决并补齐规格登记？

**一句话问题**：`regulatory_versions.json` 已是 `RESOLVED` + `by_period_end`，但 01 §〇 仍写"未裁决"。要不要把已生效的事实写进唯一权威？

**已核实事实**

| 位置 | 现状 | 应为 |
|---|---|---|
| `regulatory_versions.json` 实际 sha256 | `0fba0f30808bea310aaccf61fea4a3130455ae296fa0335debd675a3c29584d6` | — |
| 01 §〇 `REGULATORY_VERSIONS_SHA256` | `9a47dad3…84378d5c2e7ac`（旧值） | 更新 |
| 01 §〇 未决项 1 | "solution-architect 裁决；未裁决前 E1 判定程序不得运行" | 改"已解除"，**保留该句作历史条款**以免 `test_unresolved_gates_are_explicit` L128 失效 |
| `anchors.json` E1 `blocked_until` | 仍写 `UNRESOLVED` | 改 `null` |
| `tests/test_spec.py:104` | 断言 `== "UNRESOLVED"` | 改断言 |
| `tests/test_e1_judge.py` | 12 失败（2 断言 + 1 异常预期 + 9 缺 `report_year`） | 同步 |
| `pytest -q` | 14 failed / 20 passed | 目标 34 passed |

`ANCHOR_REGISTRY_SHA256` 当前 `3f9da983…` 与文件一致；**若改 `anchors.json.blocked_until`，其 sha 会变，01 §〇 需同步重算两个 sha**。

| 选项 | 含义 | 后果 |
|---|---|---|
| **A（推荐）** | 追认 `by_period_end`，统一同步 | E1 gate 解除，U-H1 可启动；14 failed → 0。属 05 C3 MAJOR（改 01），需你这一句批准 |
| B | 回滚到 `UNRESOLVED` | 撤销此前裁决，E1 继续停机，已下载 MD 缓存作废为验证用途 |
| C | 改判 `by_disclosure_date` | 交付表 11 列中**无披露日期字段**（已查 `reconciled_report` 全部列名），须另证可得性 + 重跑全部 E |

**批准 A 后我改的文件（按顺序）**
1. `annual_semi_extraction/spec/anchors.json` — E1 `blocked_until` → `null`
2. 重算 `anchors.json` / `regulatory_versions.json` 两个 sha256
3. `deliverables/01-requirement.md` §〇 — 两个 sha 登记、未决项 1 改"已解除（by_period_end，Human Gate 2026-11-13 追认）"、变更登记加一行
4. `tests/test_spec.py` — L104 改为断言 `RESOLVED` 且 `applicability_rule == "by_period_end"`
5. `tests/test_e1_judge.py` — 2 个 init 断言改 `True`；`test_resolve_version_unresolved` 改为验证已裁决不再抛错；9 处调用补 `report_year=`
6. `annual_semi_extraction/e1_judge.py` — `report_id` 改为显式复用上游 `slot_key()`（铁律 4；当前 `f"{code}_{year}_{period}"` 格式相同但未复用公共类型）
7. `deliverables/05-consumer-contract.md` — **不改条款**（C2.4 是通用规则，未决清单解除后自然不再阻断），仅在本文留痕
8. 跑 `pytest -q` 验证 34 passed 并回填留痕区

---

## ② 源 HTML / 年报 PDF 是否纳入取数契约？

**一句话问题**：要不要为下游引入 MD 之外的第二原始信源？

**已核实事实**：`reconciled_report` 全部 11 列 = `stock_code, report_year, period, winner_source, winner_native_id, winner_md_path, candidate_count, selection_rule, created_at, content_sha256, fingerprint`，**无任何 PDF/HTML 路径或桶键字段**。但上游 `dual_channel.py` 在生产时确实用了 `source/html/{code}/{native_id}.html` 与 `/backup/bulletin/source/pdf`（见交叉知识 #15）——这是"上游实然"，不是"下游授权"。01 §四 / `anchors.json.forbidden_sources` 明确禁止；04 §1 记载其 DROP 由 Human Gate 批准。

> **推荐项已因交叉核对而修正**：06 提案原写"用 MD 内目录页/正文双路径替代 HTML"，但上游 #6 已有 HTML/PDF 双通道 + Jaccard 0.3，自建属重复实现。

| 选项 | 含义 | 后果 |
|---|---|---|
| **A（推荐，含义已改）** | **不纳入**，不新建取数链路；改为**复用上游已有能力**（`canonical` 15 类映射、`extract_heading_signature`、`is_toc`、`jaccard_distance`、`report_patterns.json`、`proof` 产物）作为只读参考，不碰源字节 | 零越界、零重复实现、立即可做。E4 双路径若需真跑，先用上游 `candidate_count` / `multi_source` 代理，或确认产物是否在 RustFS |
| B | 纳入源 HTML / PDF 到下游 §四 | MAJOR：改 01 R'0 + §四 + `anchors.json` + `tests/test_spec.py` + 新建取数适配；涉及退役资产，且本地 `artifacts/` 为空 → 可得性未证 |
| C | 下游自建 MD 内目录/正文双路径 | 零越界但**重复实现**上游 #4/#6，违铁律 4；仅当 A 的只读参考不可得时才考虑 |

**推荐 A**：上游已经算过并冻结了阈值，下游要做的是**消费结论 / 复用能力**，不是重新采数据或重新造算法。批准 A 后不改任何文件，仅留痕。

---

## ③ `k`、`ε`、难度层、判别对构造规则

**只需回复"默认"。** 交叉核对后推荐项改为：**直接继承上游已冻结参数，不新造数字**。

| 参数 | 06 原拟 | **修正后推荐（继承上游）** | 上游出处 |
|---|---|---|---|
| 停止判据 | `k=30` + Chao1 上界 ≤1 | **S-3 单调收敛 `monotonic_check=pass`**（`M_i ⊆ M_{i-1}`，每轮差集有 receipt）+ 终态 `Mn=∅` 或全 `UNOBTAINABLE` | 上游 01 S-3 / F-008；`proof-2018-final.json` 实测 M0=2030→M1=0 |
| 边际覆盖 ε | 0.1%（≈37 份） | **不设**：上游 02 已裁决「无需补 357 条 patterns」，`extract_heading_signature` 只用完整 15 类 canonical 变体映射 | `02-technical-solution.md` 风险表 |
| 分歧阈值 | 无 | **`DIVERGENT_THRESHOLD = 0.3`**（Jaccard 距离，D-3 冻结） | `dual_channel.py:49` |
| 分层 | 自拟 6 维 | **`year × period × source`**，每层 ~5%（最少 1 个），覆盖率 100% | 上游 01 F-013 / §7.4 / §5 标准 6 |
| 人工通过线 | 无 | **人工 pass ≥95%**（核对 MD 与原始 PDF 章节级一致性） | 上游 01 §5 标准 6 |
| 难度层 | 自拟 L0–L3 | **用上游现成可观测代理**：`candidate_count`（`single_source` vs `multi_source`）、`winner_source`、`selection_rule`（`backup_l0/l1/l2`）、`unobtainable_reason` | 上游 01 §5 标准 5；`completeness_2021_2024.json` |
| 一级标题组合标识 | 自拟 | **F-012 结构指纹**：章节标题序列的 SHA-256 | 上游 01 F-012 |
| 残差集基线 | 自拟 | `expected 37,406 / delivered 36,969 / unobtainable 437`（全 `source_403_blocked`）+ `by_year_period` 八层 | `completeness_2021_2024.json` |
| 判别对 | 自拟 P1/P2/P3 | **沿用上游多源交叉**：同 `(code,year,period)` 的 `candidate_count>=2` 槽位即天然判别对（只差 `source`）；`single_source` 单列 | 上游 01 §5 标准 5 |

> **顺带解决 01 §五.2 的内在矛盾**：原文「同一 code/year/period、只差一个变量」字面上无法构造（一个 slot 只有一份 MD）。上游的 `multi_source` 槽位正是它的正确解释——同一 slot 的两个不同 `source` 候选。推荐在 06 中按此解释性细化，**不改写 01 原文**。

| 选项 | 含义 |
|---|---|
| **默认（推荐）** | 全盘继承上表，不新造 k/ε/难度层；我据此重写 06 的 U-H1.3/U-H1.7 |
| 自定义 | 你给出要覆盖的具体参数（如 `③ 分层加板块`），其余仍继承 |

---

## ④ 本提案（06）是否合入 01？

**一句话问题**：现在就把 U-H1 写进唯一权威，还是先当执行参考？

| 选项 | 含义 | 后果 |
|---|---|---|
| **A（推荐）** | 暂不合入，06 保持"无 Authority 执行参考" | 零变更成本；且交叉核对显示 06 的"两本 pattern / replay set / MD 双路径"多处与上游 #1–#11 重叠，**须先做资产映射、按铁律 4 收敛**，否则合入即固化重复实现。等 U-H1 通过 E1 门禁再按 05 C3 复议 |
| B | 现在合入 | MAJOR + 改 01 + 三个 sha + `tests/test_spec.py` + 重跑全部 E；且 U-H1 未经任何 E 验证，会把未验证且可能重复的内容写进唯一权威 |
| C | 废弃 06，沿用现有 `e1_judge.py` | 不推荐：手敲关键词表违 R'1②⑥、模糊阈值无外部身份、清洗销毁 verbatim span 违 M2 |

**推荐 A**：04 提案的先例正是"先无 Authority、经批准后合入"；06 应走同一路径，且先补上游资产映射。批准 A 后不改 01。

---

## 裁决留痕区（已回填）

**裁决输入**：`1. A 2.A 3 默认 4.A` — 用户 2026-11-13 12:49。

| 项 | 裁决 | 时间 | 执行状态 |
|---|---|---|---|
| ① | **A** 追认 `by_period_end` | 2026-11-13 12:49 | ✅ 已执行，见下 |
| ② | **A** 不纳入，复用上游能力 | 2026-11-13 12:49 | ✅ 不改任何授权边界，仅留痕 |
| ③ | **默认** = 继承上游冻结参数 | 2026-11-13 12:49 | ✅ 06 的 U-H1.3 / U-H1.7 已改写 |
| ④ | **A** 暂不合入 01 | 2026-11-13 12:49 | ✅ 01 正文 R'0-R'9 / E1-E6 未改，06 保持无 Authority |

### ① 实际改动清单

| 文件 | 改动 |
|---|---|
| `annual_semi_extraction/spec/anchors.json` | E1 `blocked_until` → `null`；新增 `gate_note`；`decision_procedure` 改为 `reg_version(period, report_year)` 并注明 `by_period_end`。新 sha `cb4aeb67…2f33b135` |
| `deliverables/01-requirement.md` §〇 | `ANCHOR_REGISTRY_SHA256` → `cb4aeb67…`、`REGULATORY_VERSIONS_SHA256` → `0fba0f30…`；变更登记新增 2 行 + **变更登记 v2.1**；未决项 1 改为「已解除（by_period_end）」，保留「未裁决前 E1 判定程序不得运行」作历史条款 |
| `tests/test_spec.py` | L104 断言改为 `RESOLVED` + `by_period_end`；`test_unresolved_gates_are_explicit` 增加 `by_period_end` / `Human Gate 2026-11-13 追认` 正向断言 |
| `tests/test_e1_judge.py` | 2 个 init 断言 → `True`；`test_resolve_version_unresolved` → `test_resolve_version_resolved`；7 处 `resolve_version()` + 5 处 `judge()` 补 `report_year`；5 个假 `report_id` → 合法 `slot_key`；新增 `test_report_id_mismatch_rejected`（串报告防护） |
| `annual_semi_extraction/e1_judge.py` | `judge()` 惰性复用上游 `parse_slot_key` 校验 `report_id` 与 `period`/`report_year` 一致性（防串报告，上游缺席时跳过）；`main()` 补 `report_year`；3 处「待 Human Gate」文档表述更新 |
| `scripts/batch_e1_validation.py` | `report_id = slot_key(stock_code, year, period)`（铁律 4，替代自写 f-string） |
| `deliverables/05-consumer-contract.md` | **未改条款**；C2.4 为通用规则，未决清单解除后自然不再阻断 E1 |
| `deliverables/06-heading-pattern-accumulation-proposal.md` | 升级 v2：U-H1.0 标注 gate 已解除、U-H1.2/1.3/1.4/1.7 按 ②③④ 改写、§三/§五/§六/§七同步 |

### 验收结果

```
python -m pytest -q  →  35 passed in 1.02s
```
（34 个原有/修复 + 1 个新增串报告防护测试；目标原写 34，因新增测试为 35）

- ✅ 三份注册表 sha 与 01 §〇 登记一致（`test_registry_pins_match_actual_files` 通过）
- ✅ E1 gate 状态在 01 / `anchors.json` / `test_spec.py` / `regulatory_versions.json` 四处一致
- ✅ `python -m annual_semi_extraction.e1_judge` 示例运行：合规 100%，`NOT_APPLICABLE` 正确识别第八/第九节
- ✅ `scripts/batch_e1_validation.py --help` 导入 `slot_key` 正常
- ✅ 零新增依赖（`test_no_new_dependencies_were_added` 通过）

**遗留（本次裁决未覆盖，需后续 Human 动作）**：
1. 上游 `dual_channel_report.json` / `divergent.jsonl` 本地 `artifacts/` 无落盘 → E4 双路径只能以 `candidate_count`/`multi_source` 代理，除非确认产物在 pro 主机 / RustFS。
2. 「U-H1 → 上游资产映射表」未产出 → 是 ④ 合入 01 的前置条件。
3. `chapter_extractor.py` 手敲 `CHAPTER_KEYWORDS` + 清洗销毁 verbatim span（违 M2 / R'1②⑥）仍未修复。
4. 此前 `BLOCKED_ON_GATE` 期间产出的 `e1_validation_test.json` 等结论**全部作废**，不得复用。

---

**END OF DOCUMENT**
