# AGENTS.md — nooshare-annual-semi-extraction 工作约定

## 公共仓库文档禁令（硬约束）

本仓库是 public repo，以下规则优先于任何“按需写文档”的冲动：

1. **禁止文档目录**：不得新建或保留 `docs/`、`doc/`、`deliverables/`、`reports/`、`notes/`、`specs/`、`decisions/`、`history/` 等文档或过程目录。
2. **禁止生成文字材料**：需求、设计、方案、报告、指南、评审记录、笔记等文字文件（`.md` / `.rst` / `.pdf` / `.docx` 等）不得在本仓库生成或提交。机器验证的临时输出只能写入被忽略的 `.runtime/`，不作为文档维护。
3. **README.md 只做入口**：仅保留标题与一句话定位。`AGENTS.md` 只放规则与路由。
4. **文字材料唯一归属**：所有文字材料必须维护在私有仓库 `nooshare-design` 的 `implementation-docs/nooshare-annual-semi-extraction/` 下；本仓库只引用，不复制。
5. **违规处理**：发现本仓库出现上述目录或文字材料，不就地修订——先迁移到 nooshare-design，再删除本地文件，并更新下方索引表。

**例外（数据资产，不是文字材料）**：`data/md_samples/`（测试输入样本）、`data/*.txt`（冻结集 sha256 锚）、`annual_semi_extraction/spec/regulatory_texts/*.pdf`（法规原文，sha256 已登记在规格中）属于测试数据/规格资产，保留在本仓库；不得挪动或改写，改动须同步规格与测试。

### 文字材料索引（nooshare-design）

全部 42 份材料逐文件列示；权威正文只在 nooshare-design，本仓库不复制。

#### deliverables/ — 需求、提案、规格与交付（22 份）

| 材料 | 权威位置（nooshare-design） |
|------|------------------------------|
| 冻结需求 v2（R'0-R'9 / E1-E6 唯一权威） | `implementation-docs/nooshare-annual-semi-extraction/deliverables/01-requirement.md` |
| Framing & Chunks 深度需求重写 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/02-framing-deep-requirements.md` |
| Framing & Chunks 落地策略与执行手册 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/03-framing-execution-plan.md` |
| R'0-R'9 深度重写提案（01 的 delta） | `implementation-docs/nooshare-annual-semi-extraction/deliverables/04-deep-rewrite-proposal.md` |
| 特征矩阵消费者与维护规则契约 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/05-consumer-contract.md` |
| 一级标题 Pattern 积累法提案 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/06-heading-pattern-accumulation-proposal.md` |
| 施工手册：更深版本的文档结构识别 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/07-01-施工手册-更深版本的文档结构识别.md` |
| 最终报告：三源交叉、根因审计与落地结果 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/07-02-最终报告-三源交叉与根因审计.md` |
| 四项裁决决策单（决策记录，非规格） | `implementation-docs/nooshare-annual-semi-extraction/deliverables/07-gate-decision-sheet.md` |
| 一级标题 Codebook（测量学根基 v1） | `implementation-docs/nooshare-annual-semi-extraction/deliverables/08-heading-codebook.md` |
| 会话总结：A 股年报/半年报 H1 标题抽取体系 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/08-SESSION-SUMMARY-技术上下文与状态.md` |
| 一级标题积累法：全量实证报告与需求重写 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/09-heading-empirical-report.md` |
| 金标准预标注分析报告 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/09-预标注分析报告.md` |
| 是否需要识别一级标题：前提审查 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/10-heading-necessity-analysis.md` |
| 一级标题误识别修正：形态建模 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/11-heading-morphology-correction.md` |
| 编号组合提取：更深版本 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/12-numbering-combos.md` |
| H1 全量提取：方法文档与交付清单 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/13-h1-full-extraction.md` |
| H1 组合修正与融合规格（C0-C6） | `implementation-docs/nooshare-annual-semi-extraction/deliverables/14-h1-combo-correction-spec.md` |
| H1 组合修正与融合交付报告 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/15-h1-combo-correction-report.md` |
| 重构交付报告 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/15-refactoring-report.md` |
| 冻结组合库四步落地报告 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/16-冻结组合库四步落地报告.md` |
| H1 提取器校验报告 | `implementation-docs/nooshare-annual-semi-extraction/deliverables/h1_validation_report.md` |

#### reports/ — 验证报告（4 份）

| 材料 | 权威位置（nooshare-design） |
|------|------------------------------|
| PDF 字体指纹通道验证报告（阶段 0） | `implementation-docs/nooshare-annual-semi-extraction/reports/pdf_validation_report.md` |
| 阶段 1a 扩量回归验证报告 | `implementation-docs/nooshare-annual-semi-extraction/reports/pdf_validation_report_1a.md` |
| 阶段 2 长尾修复验证报告 | `implementation-docs/nooshare-annual-semi-extraction/reports/pdf_validation_report_2.md` |
| 阶段 1b 金标准标注指南 | `implementation-docs/nooshare-annual-semi-extraction/reports/stage1b_label_guide.md` |

#### memory/ — 过程档案（3 份）

| 材料 | 权威位置（nooshare-design） |
|------|------------------------------|
| 过程档案 | `implementation-docs/nooshare-annual-semi-extraction/memory/2026-11-13.md` |
| 过程档案（外部评估意见落地研判） | `implementation-docs/nooshare-annual-semi-extraction/memory/2026-11-14.md` |
| 过程档案 | `implementation-docs/nooshare-annual-semi-extraction/memory/2026-11-15.md` |

#### 归档 README（1 份）

| 材料 | 权威位置（nooshare-design） |
|------|------------------------------|
| README 原文归档 | `implementation-docs/nooshare-annual-semi-extraction/README-full.md` |

通过 `workspace.yaml` 定位 nooshare-design 的 checkout 路径后读取上述文件。

## 铁律

1. **spec-driven**：所有实现以 nooshare-design 的 `implementation-docs/nooshare-annual-semi-extraction/deliverables/01-requirement.md`（v2）的 R'0-R'9 为唯一权威。每个 R 绑外部客观标准（E1-E6），做完了对得上锚才算数，做不上即 fail——不允许“做出来了”就交付。
   - 锚身份注册表 `annual_semi_extraction/spec/anchors.json`、法规版本表 `annual_semi_extraction/spec/regulatory_versions.json`；两者 sha256 登记在 01 §〇，由 `tests/test_spec.py` 校验，改动未同步即测试失败。
   - `02` / `03` / `04` 为执行参考 / 归档，**非需求权威**；其 R'' / R''' 编号与另一套 E1-E6 语义已作废。详细清单见上方文字材料索引。
2. **取数边界**：只走 PG 交付表 + RustFS GET，禁止直连 /backup。
3. **可复现**：特征矩阵带四元 hash 锚（输入 sha set + 词典版本 + 分词器版本 + 管线 commit）；同输入同版本 byte-identical 重跑可证（E4）。
4. **简洁为荣**：禁止重复实现、过度封装；优先复用上游 nooshare-annual-semi 已有能力（SlotKey/slot_key 等公共类型）。
5. **中文注释**：仅核心逻辑/算法/边界/易错点加注释说明“为什么”。

## 上下游

- 上游：`nooshare-annual-semi`（语料生产 + 完备性证明，已封版，不修改上游代码）
- 本 repo 消费：交付表 `annual_semi.reconciled_report` + RustFS 桶对象
- 二期下游（未来）：`nooshare-annual-semi-research`（研究验证，消费本 repo 的特征矩阵）

## 失控防御（本 repo 存在的理由）

上一个 `ashare-bulletin-recognition` 因 agent 低智能无规格开发而失控被废。本 repo 的对抗机制：
- R'0-R'9 冻结在先，代码在后
- 每个 R 绑外部锚（监管准则/量化 DB/未来业绩/hash 复现/缺失机制/问询函）
- 任何 unit 完成后必须跑对应 E 标准，不过不许合入

## 主机约束

本仓库只在 pro 主机开发和运行。禁止 clone 到 Windows 主机（travis-hp）。如果在 Windows 主机上发现本仓库的 checkout，应删除该 checkout 并修正来源（不正确的 clone 操作或 workspace 配置）。
