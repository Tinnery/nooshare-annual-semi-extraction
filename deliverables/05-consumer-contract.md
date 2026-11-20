# 特征矩阵消费者与维护规则契约

> Date: 2026-11-13
> Status: **生效（scoped contract）**
> Authority Layer: 契约层，**不定义需求**；需求唯一权威为 `deliverables/01-requirement.md`（v2）
> 依据：01 v2 §六；`ashare-project` 参考证据（见 §一）

---

## 〇、为什么需要这份契约

01 v2 §六已指出：本 repo 的特征矩阵当前**没有运行时消费者**。参考生态已经因为同一件事付出过代价：

| 证据 | 事实 |
|---|---|
| `ashare-project/changes/historical/2026-09-29-frame-v2-experiment/evidence/outputs/f0-statistics.md:150-160` | `report_frame` 18,231,500 行、`report_frame_v2`、Qdrant `ashare_report_frames` 的 Consumer 全部 **NONE FOUND**；`is_valuable = true` 为 0 / 18,231,500；`llm_model NOT NULL` 为 0 |
| `ashare-project/engineering/contracts/jq-decoded-artifact.md:517-519` | 事后结论：「It had no consumer and no maintenance rule. No schema version, no validation, no reader.」 |
| `ashare-project/README.md:99-112` | 「实然不证应然」；「Agent 不能 invent project authority」 |

**结论**：在消费者缺位时，E1-E6 是唯一能替消费者判定对错的机制。因此 01 v2 §2.3 禁止把验收换成检索类指标；本契约负责把"消费者出现时怎么办"提前定死，避免再产出一层无人读取的数据。

---

## 一、事实基线（实然，不作应然）

| 项 | 当前状态 |
|---|---|
| 一期产出 | 特征矩阵（R'0-R'6），DVC 版本化 + 四/五元 hash 锚 |
| 运行时消费者数量 | **0** |
| 名义消费者 | 二期 `nooshare-annual-semi-research`（**未来 repo，尚不存在**，01 v2 §一） |
| 上游消费者 | 无（上游 `nooshare-annual-semi` 已封版，方向单向：本 repo 消费上游） |
| 判定代行 | E1-E6（01 v2 §2.3）+ `tests/test_spec.py` 规格不变量 |

**禁止把"0 个消费者"写成"已有下游验证"**。任何报告中出现"已交付验证""下游可直接使用"字样，必须同时给出消费者标识与接入证据。

---

## 二、C1 消费界面（消费者必须读到什么）

特征矩阵的每个可消费单元必须自带以下字段，缺一即视为不可消费（与 01 v2 M2 一致）：

| 组 | 字段 | 来源 |
|---|---|---|
| 身份 | `slot_key`（复用上游公共类型，铁律 4）、`stock_code`、`year`、`period` | 交付表 |
| 语义五元组 | `concept`, `period`, `scope`（合并/母公司）, `unit`, `value` | R'2 / R'4 |
| 可反驳证据 | `source_hash`、`start_offset`、`end_offset`、原文 verbatim span | M2 / `frame-v2.md` 字段语义 |
| 结构定位 | `semantic_path`、`resolution_state`（四态，不自造枚举） | R'6 |
| 合规 | `chapter_compliance`、三态缺失标记（NOT_APPLICABLE / NOT_DISCLOSED / EXTRACTION_FAILURE） | R'1 / R'7 |
| 复现 | 四/五元 hash 锚、词典版本、分词器版本、判定程序 commit、管线 commit | R'6 / M3 |
| 分歧 | `evidence` 表（对账失败不静默丢弃） | R'4 |
| 版本 | `feature_schema_version`（semver） | 本契约 C3 |

---

## 三、C2 消费者缺位期间的判定代行

1. **代行规则**：在消费者出现前，一个 unit 是否可合入，只由它绑定的 E 判定程序决定（01 v2 §五.1）。E 不过即 fail，不允许"待修复"无限期挂起。
2. **禁止替代**：不得以 Recall@10、cell-level 人工准确率、Cohen's κ、引用覆盖率、多粒度提升 10% 等替代 E1-E6——它们服务于本 repo 不存在的 RAG 产品（01 v2 §2.3）。
3. **可交付 ≠ 已消费**：E 全通过后，矩阵状态为 `DELIVERABLE`（可交付）；只有存在消费者接入证据时才能标 `CONSUMED`。
4. **前提未裁决时停机**：01 v2 §〇 未决项 1-3 未裁决前，相关 E 判定程序不得运行；此时矩阵状态必须为 `BLOCKED_ON_GATE`，不得标 `DELIVERABLE`。

---

## 四、C3 schema 版本演进

| 变更类型 | 例子 | 允许方 | 必须动作 |
|---|---|---|---|
| PATCH | 修 bug、不改列名/语义 | Agent（SAFE-ITERATE） | 重跑受影响 E；`feature_schema_version` patch +1 |
| MINOR | 新增可选列 | Agent + 变更登记 | 重跑全部 E；登记到 01 §〇变更登记 |
| MAJOR | 改列名/语义/单位口径、删列、换锚定义 | **Human Gate**（solution-architect） | 改 01 v2；重跑全部 E；同步本契约 C1；下游接入确认 |

- 任何改变 **E1-E6 语义或锚身份** 的动作，一律 MAJOR，且必须同步 `annual_semi_extraction/spec/anchors.json`、01 §〇 的 sha 登记与 `tests/test_spec.py`。
- 禁止产生新的 Requirement 代际（R''''）；变更只改 01 v2 本体。

---

## 五、C4 维护规则（什么变化触发什么重跑）

| 触发源 | 锚定位置 | 触发动作 |
|---|---|---|
| 输入 MD sha set 变化 | 四元 hash 锚 | 重跑受影响 slot 的全部 E |
| 词典原文 / 衍生脚本变化 | 词典版本 + commit | 重跑 E3 / E4 |
| 分词器版本变化 | 分词器版本 hash | 重跑 E2 / E4 |
| 法规原文采集 / 版本表变更 | `regulatory_versions.json` + 01 §〇 sha 登记 | 重跑 E1，并重算 `chapter_compliance` |
| 判定程序 / 归一化函数变化 | commit + 函数版本 | 重跑**全部** E（M3） |
| 锚注册表变更 | `anchors.json` sha | `tests/test_spec.py` 失败 → 强制走变更流程 |
| 管线 commit 变化 | 四元 hash 锚 | 重跑 E4（byte-identical + 双路径收敛） |

**维护责任人**：本 repo（Agent 可执行 PATCH/MINOR 的具体化）；语义跃迁由 Human 裁决。上游 `nooshare-annual-semi` 已封版，**不修改上游**。

---

## 六、C5 过期判定与启动条件

1. **消费者出现时**：`nooshare-annual-semi-research`（或其替代）落地后，须在本契约登记 `consumer_id`、`consumes_columns`、`first_read_at`、`schema_version_pinned`。
2. **接入期限**：登记后若 90 天内无实际读取证据，矩阵状态回落为 `UNCONSUMED`，不得在任何报告中声称"已交付给下游"。
3. **反向保护**：在消费者出现**之前**，不得为了"将来可能被用"而扩列、扩索引、扩粒度——这正是参考生态 18,231,500 帧 0 consumer 的成因。新增列必须有当前 E 判定需要或 Human 裁决依据。
4. **读者缺失即停机**：若某次产出没有任何 `tests/test_spec.py` 之外的读取者，且不属于 E 判定所需，视为过度实现，按铁律 4「简洁为荣」回收。

---

## 七、C6 禁止项

- 不新建表（复用 R'4 已有 evidence 表）；不引入新依赖（01 v2 落地为零新增依赖）。
- 不恢复 trash、不读取 `source/html/*` / `sina_bulletin.db`（01 v2 §四）。
- 不把审计事实当作需求授权；不把 `DELIVERABLE` 写成 `CONSUMED`。
- 不在消费者缺位期间引入 RAG 检索指标或向量索引主链路。

---

## 八、契约自检清单（可由 `tests/test_spec.py` 扩展）

| # | 检查 | 当前期望 |
|---|---|---|
| 1 | 01 v2 是否声明唯一权威 | 是 |
| 2 | 02/03 是否已标注非需求权威 | 是 |
| 3 | 锚注册表 sha 是否与 01 §〇 登记一致 | 是 |
| 4 | 法规版本表 sha 是否与 01 §〇 登记一致 | 是 |
| 5 | 授权数据源是否只有交付表 + RustFS GET | 是 |
| 6 | 是否声明"当前 0 消费者" | 是（本文 §一） |
| 7 | 法规原文 sha 是否仍未采集（禁止臆造） | 是，`PENDING_ACQUISITION` |

---

**未决**：`consumer_id` 与 `first_read_at` 当前为空，属正常状态，不是缺陷；不得推断填空（参考生态「不推断填空」）。
