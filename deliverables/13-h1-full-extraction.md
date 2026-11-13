# H1 全量提取：方法文档与交付清单

**生成时间**：2026-11-13  
**提取器版本**：v2_reg_anchored  
**处理规模**：38,350 份年报/半年报

---

## 1. 方法概述

### 1.1 核心理念：监管锚定的确定性提取

H1（一级章节标题）提取采用**监管锚定**策略：以证监会/交易所法规规定的章节模板为"oracle"，通过前缀双向匹配将实报中的章节标题对齐到法规模板。

**关键设计原则**：

1. **抽取-校验分离**：提取阶段只做质量门控（像不像一组顶层章节），不做齐全性裁决；校验阶段按规范类别与法规模板比对
2. **规范类别匹配**：不依赖序号位置，而是将章节标题映射到规范类别（如 `mda`、`governance`、`financial`），对 A+H 重编号、章节合并/拆分鲁棒
3. **前缀双向匹配**：heading 是 legal 前缀（截断）或 legal 是 heading 前缀（扩展）都算命中
4. **全行扫描**：不只扫描 `# ` 行，纯文本行、TOC 行都纳入候选

### 1.2 技术架构

```
输入：38,350 份 MD 格式年报/半年报
  ↓
[1] 全行扫描 + 编号识别
    - 5 种编号系统：CH_ZH（第一章）、CN_DUN（一、）、AR_DOT（1.）、AR_PAREN（(1)）、PAREN_CN（(一)）
    - 粘连行剥离：报告标题与章节标题粘在同一行时，先剥离标题前缀
  ↓
[2] 候选集合质量门控
    - 序数去重：1..ORD_CAP（15），超出视为脚注噪声
    - 法定名命中率 ≥0.3：容纳非 A 股模板（退市/三板）
    - H1 层一律接受，非 H1 层仅当"像标题"才接受
  ↓
[3] 规范类别映射
    - 上游 `_map_heading_to_category`：映射到 15+ 规范类别
    - 本地变体表回退：覆盖 A+H 股变体（如"股份变动及主要股东持股情况"→`shares`）
  ↓
[4] 监管覆盖率校验
    - 按 reg_version 选择法规模板（2021-2024 vs 2025+）
    - 比对 present_cats 与模板的 always sections
    - 条件节（优先股/债券）依法可省略，不算失败
  ↓
输出：JSONL（每文件一行）+ PG 入库
```

### 1.3 reg_version 映射规则

| 报告期间 | 年份范围 | reg_version | 应披节数 |
|---------|---------|-------------|---------|
| 年报 | 2021-2024 | `no2_2021_15` | 10（8 always + 2 conditional） |
| 半年报 | 2021-2024 | `no3_2021_16` | 10（8 always + 2 conditional） |
| 年报 | 2025+ | `no2_2025_3` | 8（全部 always） |
| 半年报 | 2025+ | `no3_2025_4` | 8（全部 always） |

**conditional sections**：第 8 节（优先股）、第 9 节（债券），仅当公司存在相关业务时才必须披露。

---

## 2. 全量执行结果

### 2.1 总体统计

| 指标 | 数值 |
|------|------|
| 总处理报告数 | 38,350 |
| 完整提取（应披节全在） | 35,386 (92.3%) |
| 残差（不完整/无） | 2,964 (7.7%) |
| 平均每文件一级标题数 | 10.7 |

### 2.2 方法分布

| 方法 | 报告数 | 占比 | 说明 |
|------|--------|------|------|
| `ch_zh` | 37,384 | 97.5% | 中文编号（第一章、第二节） |
| `md_h1` | 870 | 2.3% | Markdown H1 但无编号 |
| `none` | 95 | 0.2% | 未提取到任何章节 |
| `cn_dun` | 1 | 0.0% | 中文顿号编号（一、二、三） |

### 2.3 跨年稳定性

| 年份 | 报告数 | 完整数 | 完整率 |
|------|--------|--------|--------|
| 2021 | 8,281 | 6,663 | 80.5% |
| 2022 | 9,357 | 8,836 | 94.4% |
| 2023 | 10,150 | 9,673 | 95.3% |
| 2024 | 10,562 | 10,214 | 96.7% |

**观察**：2021 年完整率较低（80.5%），2022 年后稳定在 94-97%。早期报告格式更不规范，TOC 与正文结构差异更大。

### 2.4 高频缺失应披节

| 缺失节 | 缺失次数 | 典型原因 |
|--------|---------|---------|
| 第 2 节（公司简介和主要财务指标） | 2,011 | 三板/退市报告模板不同 |
| 第 3 节（管理层讨论与分析） | 1,984 | A+H 股拆分为多节 |
| 第 5 节（环境和社会责任） | 1,858 | 早期报告未单列 ESG |
| 第 7 节（股份变动及股东情况） | 1,433 | A+H 股重编号 |
| 第 10 节（财务报告） | 1,320 | 半年报可能无独立财务报告节 |

---

## 3. PostgreSQL 入库

### 3.1 表结构

**`annual_semi.h1_report_summary`**：报告级汇总

```sql
CREATE TABLE annual_semi.h1_report_summary (
    slot_key        TEXT PRIMARY KEY,  -- {stock_code}_{year}_{period}
    stock_code      TEXT NOT NULL,
    report_year     INT NOT NULL,
    period          INT NOT NULL,      -- 4=年报, 2=半年报
    source_sha256   TEXT,              -- 源文件 SHA256
    n_bytes         BIGINT,
    extraction_method TEXT,            -- ch_zh/md_h1/cn_dun/none
    n_headings      INT,
    is_complete_l1  BOOLEAN,           -- 应披节是否全在
    coverage_ratio  NUMERIC(6,4),      -- 监管覆盖率
    missing_always_sections INT[],     -- 缺失的 always 节序号
    missing_conditional_sections INT[],
    reg_version     TEXT,              -- 法规模板版本
    expected_sections INT,
    dual_agreement  NUMERIC(6,4),      -- 双通道一致率
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

**`annual_semi.h1_heading_detail`**：标题明细

```sql
CREATE TABLE annual_semi.h1_heading_detail (
    id              BIGSERIAL PRIMARY KEY,
    slot_key        TEXT NOT NULL REFERENCES annual_semi.h1_report_summary(slot_key),
    ordinal         INT,               -- 章节序号
    marker          TEXT,              -- 编号标记（如"第一章"）
    raw_name        TEXT,              -- 原始标题文本
    canonical_name  TEXT,              -- 规范化名称（前缀双向匹配结果）
    canonical_cat   TEXT,              -- 规范类别（mda/governance/financial 等）
    line_no         INT,               -- 行号
    byte_start      BIGINT,            -- 字节起始位置
    byte_end        BIGINT,            -- 字节结束位置
    md_level        INT,               -- Markdown 层级（0=纯文本, 1=#, 2=##）
    numbering_system TEXT,             -- 编号系统（CH_ZH/CN_DUN/AR_DOT 等）
    verbatim_line   TEXT,              -- 原始行文本（截断至 500 字符）
    extractor_version TEXT DEFAULT 'v2_reg_anchored'
);
```

### 3.2 入库统计

| 表 | 行数 |
|----|------|
| `h1_report_summary` | 38,350 |
| `h1_heading_detail` | 411,181 |

**索引建议**（未创建，按需添加）：

```sql
CREATE INDEX idx_h1_summary_year ON annual_semi.h1_report_summary(report_year);
CREATE INDEX idx_h1_summary_complete ON annual_semi.h1_report_summary(is_complete_l1);
CREATE INDEX idx_h1_detail_slot ON annual_semi.h1_heading_detail(slot_key);
CREATE INDEX idx_h1_detail_cat ON annual_semi.h1_heading_detail(canonical_cat);
```

---

## 4. 校验报告摘要

详见 `deliverables/h1_validation_report.md`。

### 4.1 客观标准对照

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 监管覆盖率 | ≥95% | 96.9% | ✅ 达标 |
| 跨度可复现性 | 100% | 100.0% | ✅ 达标 |
| 双通道一致率 | ≥98% | 81.7% | ❌ 未达标 |
| 残差率 | ≤2% | 7.7% | ❌ 未达标 |

### 4.2 未达标项分析

**双通道一致率（81.7%）**：

- 可比样本：仅 460 份（1.2%），即只有这些报告的 TOC 与正文都能独立提取出有效章节集合
- 根因：绝大多数报告的 TOC 是点线页码格式（如"第一节 公司简介 .... 17"），与正文的 `# 第一节 公司简介` 结构差异大
- 改进方向：优化 TOC 解析逻辑，支持更多 TOC 格式变体

**残差率（7.7%）**：

- 2021 年残差率 19.5%，2024 年降至 3.3%
- 根因：早期报告格式更不规范，TOC 与正文结构差异更大；三板/退市报告模板与 A 股模板差异大
- 改进方向：扩展本地变体表，覆盖更多特殊模板；对 `md_h1` 和 `none` 方法的报告进行抽样诊断

---

## 5. 文件清单

### 5.1 提取器与脚本

| 文件 | 说明 |
|------|------|
| `scripts/h1_extractor.py` | H1 提取器主程序（v2_reg_anchored） |
| `scripts/h1_validation_report.py` | 校验报告生成器 |

### 5.2 数据产出

| 文件 | 说明 | 行数 |
|------|------|------|
| `data/h1_full.jsonl` | 全量提取结果（JSONL） | 38,350 |
| `data/h1_failures.jsonl` | 残差报告清单 | 2,964 |

### 5.3 文档产出

| 文件 | 说明 |
|------|------|
| `deliverables/13-h1-full-extraction.md` | 本文档：方法文档与交付清单 |
| `deliverables/h1_validation_report.md` | 校验报告（客观标准对照） |

### 5.4 上游依赖（只读）

| 文件 | 说明 |
|------|------|
| `annual_semi_extraction/spec/legal_chapters.json` | 法规模板（5 个 reg_version） |
| `reference/report_patterns.json` | 章节名变体模式库 |
| `scripts/heading_morphology.py` | 形态学工具（LEGAL_NAMES、RE_LEGAL） |
| `annual_semi/identify/_funcs/heading_verify.py` | 规范类别映射（`_map_heading_to_category`） |

---

## 6. 使用示例

### 6.1 从 JSONL 查询特定报告

```python
import json

with open('data/h1_full.jsonl') as f:
    for line in f:
        r = json.loads(line)
        if r['slot_key'] == '000001_2023_4':  # 平安银行 2023 年报
            print(f"方法: {r['extraction_method']}")
            print(f"完整: {r['is_complete_l1']}")
            print(f"覆盖率: {r['coverage_ratio']}")
            for h in r['headings']:
                print(f"  第{h['ordinal']}节: {h['raw_name']} [{h['canonical_cat']}]")
            break
```

### 6.2 从 PostgreSQL 查询

```python
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor(cursor_factory=RealDictCursor)

# 查询 2023 年所有完整提取的年报
cur.execute("""
    SELECT slot_key, stock_code, n_headings, coverage_ratio
    FROM annual_semi.h1_report_summary
    WHERE report_year = 2023 AND period = 4 AND is_complete_l1 = true
    ORDER BY stock_code
    LIMIT 10
""")
for row in cur.fetchall():
    print(row)

# 查询特定报告的所有标题
cur.execute("""
    SELECT ordinal, raw_name, canonical_cat, line_no
    FROM annual_semi.h1_heading_detail
    WHERE slot_key = '000001_2023_4'
    ORDER BY ordinal
""")
for row in cur.fetchall():
    print(f"第{row['ordinal']}节: {row['raw_name']} [{row['canonical_cat']}] (行{row['line_no']})")
```

### 6.3 重新运行提取器

```bash
# 全量运行
python scripts/h1_extractor.py --out data/h1_full.jsonl --failures data/h1_failures.jsonl

# 断点续传（追加模式）
python scripts/h1_extractor.py --offset 25000 --append --out data/h1_full.jsonl --failures data/h1_failures.jsonl

# 冒烟测试（前 1000 份）
python scripts/h1_extractor.py --limit 1000 --out data/h1_smoke.jsonl --failures data/h1_smoke_failures.jsonl
```

### 6.4 生成校验报告

```bash
# 从 JSONL 生成
python scripts/h1_validation_report.py --source jsonl --jsonl data/h1_full.jsonl --output deliverables/h1_validation_report.md

# 从 PostgreSQL 生成
python scripts/h1_validation_report.py --source pg --output deliverables/h1_validation_report_pg.md
```

---

## 7. 已知局限与后续优化

### 7.1 已知局限

1. **双通道一致率低**：TOC 解析逻辑不够鲁棒，只有 1.2% 的报告能同时从 TOC 和正文提取出有效章节集合
2. **早期报告残差高**：2021 年残差率 19.5%，主要因为格式不规范
3. **特殊模板覆盖不足**：三板/退市报告的章节模板与 A 股差异大，本地变体表尚未完全覆盖
4. **条件节判断简化**：优先股/债券节是否应披，当前按法规模板的 conditional 标记处理，未结合公司实际情况判断

### 7.2 后续优化方向

1. **TOC 解析增强**：支持更多 TOC 格式变体（如纯数字页码、无点线格式）
2. **残差报告抽样诊断**：对 2,964 份残差报告进行分层抽样，识别系统性失败模式
3. **本地变体表扩展**：基于残差诊断结果，持续补充 A+H 股、三板、退市等特殊模板的章节名变体
4. **条件节智能判断**：结合公司财务报表数据，判断优先股/债券节是否应披
5. **跨年稳定性监控**：建立自动化监控，当新年份报告完整率显著下降时告警

---

## 8. 结论

本次全量 H1 提取任务完成了 38,350 份年报/半年报的处理，监管覆盖率 96.9%、跨度可复现性 100%，核心指标达标。双通道一致率（81.7%）和残差率（7.7%）未达目标，但已识别根因并规划优化路径。

提取器采用监管锚定的确定性方法，通过抽取-校验分离、规范类别匹配、前缀双向匹配等技术，对 A+H 重编号、章节合并/拆分、章节名漂移等复杂场景鲁棒。全量数据已入库 PostgreSQL，支持后续下游任务（如章节内容提取、结构化分析）。

---

*文档生成时间：2026-11-13*  
*提取器版本：v2_reg_anchored*  
*处理规模：38,350 份报告*
