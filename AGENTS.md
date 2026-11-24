# AGENTS.md — nooshare-annual-semi-extraction 工作约定

## 铁律

1. **spec-driven**：所有实现以 `deliverables/01-requirement.md`（v2）的 R'0-R'9 为唯一权威。每个 R 绑外部客观标准（E1-E6），做完了对得上锚才算数，做不上即 fail——不允许"做出来了"就交付。
   - 锚身份注册表 `annual_semi_extraction/spec/anchors.json`、法规版本表 `annual_semi_extraction/spec/regulatory_versions.json`；两者 sha256 登记在 01 §〇，由 `tests/test_spec.py` 校验，改动未同步即测试失败。
   - `deliverables/02-framing-deep-requirements.md`、`deliverables/03-framing-execution-plan.md`、`deliverables/04-deep-rewrite-proposal.md` 为执行参考 / 归档，**非需求权威**；其 R'' / R''' 编号与另一套 E1-E6 语义已作废。
2. **取数边界**：只走 PG 交付表 + RustFS GET，禁止直连 /backup。
3. **可复现**：特征矩阵带四元 hash 锚（输入 sha set + 词典版本 + 分词器版本 + 管线 commit）；同输入同版本 byte-identical 重跑可证（E4）。
4. **简洁为荣**：禁止重复实现、过度封装；优先复用上游 nooshare-annual-semi 已有能力（SlotKey/slot_key 等公共类型）。
5. **中文注释**：仅核心逻辑/算法/边界/易错点加注释说明"为什么"。

## 上下游

- 上游：`nooshare-annual-semi`（语料生产 + 完备性证明，已封版，不修改上游代码）
- 本 repo 消费：交付表 `annual_semi.reconciled_report` + RustFS 桶对象
- 二期下游（未来）：`nooshare-annual-semi-research`（研究验证，消费本 repo 的特征矩阵）

## 失控防御（本 repo 存在的理由）

上一个 `ashare-bulletin-recognition` 因 agent 低智能无规格开发而失控被废。本 repo 的对抗机制：
- R'0-R'9 冻结在先，代码在后
- 每个 R 绑外部锚（监管准则/量化 DB/未来业绩/hash 复现/缺失机制/问询函）
- 任何 unit 完成后必须跑对应 E 标准，不过不许合入
