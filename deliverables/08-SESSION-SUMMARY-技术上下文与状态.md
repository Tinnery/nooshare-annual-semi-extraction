# 会话总结：A 股年报/半年报 H1 标题抽取体系

**生成时间**: 2026-11-14 02:25 CST  
**目的**: 保留技术上下文，供新会话继续工作，无需用户重新解释或重跑历史任务

---

## 一、项目目标与当前状态

### 1.1 核心目标
从 A 股年报/半年报的 MD 文件中抽取一级标题（H1），并将结果存入 PostgreSQL 数据库。

### 1.2 数据规模
- **总报告数**: 36,899 份
- **MD 完整**: 34,060 份（92.3%）
- **MD 不完整**: 2,839 份（7.7%）
  - 已有 PDF: 2,658 份
  - 无 PDF: 181 份

### 1.3 当前状态
- ✅ 阶段 3（PDF 批量下载）已暂停，停在批次 29
- ✅ 已下载 5,764 份 PDF 到 rustfs
- ✅ PG 中已有 PDF 结果 8,432 份（含阶段 2 的 301 份）
- ✅ 融合结果已写入 `h1_fused_result` 表，共 36,899 条
- ✅ 故障树分析完成，762 份 100% 归因
- ✅ 不确定性报告生成（Bootstrap 1000 次）

---

## 二、技术架构与关键文件

### 2.1 核心脚本

#### `scripts/h1_pdf_core.py` - PDF 抽取核心
- **三级策略**:
  1. `numbering`: 正则匹配 `第[一二三四五六七八九十]+节`（0.9917 准确率）
  2. `bookmark`: PDF 书签元数据（0.4373 准确率，降级）
  3. `font_fallback`: 字体大小启发式（0.58 准确率，降级）
- **超时熔断**: `signal.alarm(90)` 防止卡死
- **并行**: 12 核 Pool
- **关键函数**:
  - `extract_pdf(pdf_path, slot_key)`: 主入口
  - `norm_heading(h)`: 标题规范化
  - `match_score(hs, ref)`: 与法规基准匹配打分
  - `_canon_match(h, canon_set)`: 别名匹配

#### `scripts/stage_landing.py` - 融合落地
- **输入**: MD 结果 + PDF 结果
- **决策逻辑**:
  ```python
  if md_complete:
      use md
  else:
      if pdf_available and pdf_quality_high:
          use pdf_replace
      elif pdf_available and pdf_quality_low:
          use pdf_replace_review (需人工审核)
      else:
          use unrepairable
  ```
- **修正**: MD 不完整时，`cross<0.6` 不再判低置信（避免误伤 736 份）
- **输出**: `annual_semi.h1_fused_result` 表

#### `scripts/stage_uncertainty.py` - 不确定性量化
- **方法**: Bootstrap 1000 次重采样
- **输出**: `data/uncertainty_report.json`
- **指标**: 法规符合率 95% CI、跨管线一致性 95% CI

#### `scripts/stage_fault_tree.py` - 故障归因
- **输出**: `data/fault_tree.json`、`data/fault_cases.csv`
- **归因类别**:
  - 版式异常: 290 份
  - 算法边界: 276 份
  - 数据缺失: 181 份
  - 跨源冲突: 15 份
- **归因率**: 762/762 = 100%

### 2.2 数据库表结构（PostgreSQL）

#### `annual_semi.h1_fused_result` - 融合结果
```sql
CREATE TABLE annual_semi.h1_fused_result (
    slot_key TEXT PRIMARY KEY,          -- 如 "000001_2023_annual"
    stock_code TEXT,
    report_year INTEGER,
    period TEXT,                         -- "annual" | "semi"
    source TEXT,                         -- "md" | "pdf_replace" | "pdf_replace_review" | "pdf_low_conf" | "unrepairable"
    final_headings JSONB,                -- ["第一节 释义", "第二节 公司简介...", ...]
    n_headings INTEGER,
    confidence TEXT,                     -- "high" | "medium" | "low"
    legal_rate REAL,                     -- 法规符合率
    cross_agreement REAL,                -- 跨管线一致性
    consensus_deviation REAL,
    md_complete BOOLEAN,
    pdf_strategy TEXT,                   -- "numbering" | "bookmark" | "font_fallback" | null
    pdf_purity REAL,
    evidence JSONB,
    failure_mode TEXT,
    needs_review BOOLEAN
);
```

#### 其他表
- `h1_report_summary`: MD 抽取汇总
- `h1_heading_detail`: 标题明细
- `h1_pdf_result`: PDF 抽取结果
- `pdf_acquisition`: PDF 下载状态

### 2.3 数据文件（pro 主机）

#### `/source/annual-semi/data/`
- `h1_fused_result.csv` (23.8 MB): 融合结果 CSV
- `h1_fused_result.jsonl` (32.2 MB): 融合结果 JSONL
- `uncertainty-report.json`: 不确定性报告
- `fault-tree.json`: 故障树
- `fault-cases.csv`: 故障案例

#### `/source/annual-semi/scripts/`
- 所有核心脚本（见 2.1）

#### `/source/annual-semi/deliverables/`
- `07-01-施工手册-更深版本的文档结构识别.md`: 施工手册 v1.1
- `07-02-最终报告-三源交叉与根因审计.md`: 最终报告

### 2.4 本地文件（Windows）

#### `C:\dev\nooshare-annual-semi-extraction\`
- `scripts/`: 脚本副本（与 pro 同步）
- `data/`: 中间数据（heading_corpus.jsonl、h1_full.jsonl 等）
- `deliverables/`: 交付文档
- `.gitignore`: 排除 `data/md_cache/`、`*.pdf`、`*.tar.gz`、`h1_full*.jsonl`

---

## 三、外部标准与法规基准

### 3.1 证监会法规（真实外部标准）
- **年报**: 证监会公告〔2021〕15 号，正文十节
- **半年报**: 证监会公告〔2021〕16 号，正文十节

#### 法规基准十节（`LEGAL_10`）
```python
LEGAL_10 = [
    '重要提示、目录和释义',
    '公司简介和主要财务指标',
    '管理层讨论与分析',
    '公司治理',
    '环境和社会责任',
    '重要事项',
    '股份变动及股东情况',
    '优先股相关情况',
    '债券相关情况',
    '财务报告'
]
```

#### 别名处理
- 第一节"释义"是合法别名（`CANON_NEW_ANNUAL` / `CANON_NEW_SEMI`）
- 规范化函数 `norm_heading()` 统一处理

### 3.2 伪外部标准（已作废）
1. **目录页交叉验证**: 循环论证（`toc_headings` 与 `headings` 同源）
2. **时代指纹**: `new_annual == new_semi` 导致 era 失效
3. **11 项基准**: 分母含"备查文件目录"错误

### 3.3 质量指标
- **法规符合率**: 0.9864（95% CI [0.9856, 0.9872]）
- **跨管线一致性**: 0.8296（95% CI [0.8236, 0.8351]）
- **策略准确率**:
  - `numbering`: 0.9917
  - `bookmark`: 0.4373（降级）
  - `font_fallback`: 0.58（降级）

---

## 四、连接信息

### 4.1 PostgreSQL
```
host: pg.pro.neuralj.com
dbname: nooshare_dev
user: travis
password: sheeta-pg
schema: annual_semi
```

### 4.2 rustfs (S3)
```
endpoint: s3.rustfs.pro.neuralj.com
bucket: annual-semi
key_pattern: pdf/{code}/{slot_key}.pdf
access_key: charlie
secret_key: sheeta-rustfs
```

### 4.3 pro 主机
```bash
ssh pro
tmux attach -t stage3  # 阶段 3 会话（已暂停）
```

### 4.4 GitHub
```
repo: Tinnery/nooshare-annual-semi-extraction (private)
remote: git@github.com:Tinnery/nooshare-annual-semi-extraction.git
```

---

## 五、关键决策与修正

### 5.1 噪声组合反向修正
- **问题**: MD 不完整时，坏掉的 MD 通道否定 PDF
- **修正**: MD 不完整时，`cross<0.6` 不再判低置信
- **效果**: `pdf_replace` 1,701 → 2,163，低置信 957 → 241

### 5.2 故障树归因矛盾
- **问题**: `none:71` 与 `no_pdf:ok` 矛盾
- **修正**: `stage_landing.py` / `stage_fault_tree.py` 使用 `pdf_acquisition.status` 正确归因
- **效果**: 762 份 100% 归因

### 5.3 融合逻辑误伤
- **问题**: MD 仅 1 个噪声碎片但 PDF 完整十节，被判低置信
- **修正**: 决策树优先 PDF 质量，不再用坏掉的 MD 通道否定 PDF
- **效果**: 恢复 736 份

### 5.4 时代指纹失效
- **问题**: `new_annual == new_semi` 导致 era 无法区分
- **修正**: 改用 `report_year + period` 分支
- **效果**: 法规符合率 0.8681 → 0.9535 → 0.9864（含别名）

---

## 六、未闭环项

### 6.1 金标准验证
- **状态**: 301 份底稿已标注，但未双人标注
- **缺失**: Kappa/P/R 未计算
- **建议**: 后续可组织双人标注，计算 inter-annotator agreement

### 6.2 准确率声明
- **现状**: 报告不称"准确率"，只称"法规符合率"
- **原因**: 无真实 ground truth，法规符合率是代理指标
- **建议**: 明确声明这是启发式指标，非准确率

### 6.3 置信度校准
- **现状**: `confidence` 是启发式（high/medium/low），未校准
- **建议**: 后续可用金标准验证集校准置信度阈值

### 6.4 PDF 覆盖率
- **现状**: 2,658/2,839 已有 PDF（93.6%），181 份无 PDF
- **建议**: 可继续下载剩余 PDF，但优先级低

### 6.5 A/B 测试
- **现状**: 用户决定先积累更多 PDF 再做 A/B
- **建议**: 待 PDF 积累到 10,000+ 份时，可做 MD vs PDF 的 A/B 对比

---

## 七、施工手册要点

### 7.1 文档结构识别的三层方法
1. **法规层**: 证监会公告正文十节（真实外部标准）
2. **统计层**: 横截面众数作为统计锚点
3. **算法层**: 三级策略（numbering > bookmark > font_fallback）

### 7.2 根因审计原则
- **不扩大范围**: 不做"更大版本"，做"更深版本"
- **根因导向**: 每个故障 100% 归因到具体原因
- **外部标准优先**: 法规 > 统计 > 算法

### 7.3 决策逻辑
```python
if md_complete:
    use md
else:
    if pdf_available:
        pdf_quality = legal_rate(pdf_headings)
        if pdf_quality >= 0.8:
            use pdf_replace (high confidence)
        elif pdf_quality >= 0.6:
            use pdf_replace_review (needs review)
        else:
            use pdf_low_conf
    else:
        use unrepairable
```

---

## 八、后续工作建议

### 8.1 短期（可选）
1. **恢复阶段 3**: 继续下载剩余 PDF（优先级低）
2. **双人标注**: 组织 301 份底稿的双人标注，计算 Kappa
3. **置信度校准**: 用金标准验证集校准置信度阈值

### 8.2 中期
1. **A/B 测试**: 待 PDF 积累到 10,000+ 份时，做 MD vs PDF 对比
2. **故障案例库**: 将 762 份故障案例整理成可查询的数据库
3. **可视化报告**: 生成交互式报告（法规符合率、故障分布等）

### 8.3 长期
1. **扩展到季报**: 将方法扩展到季报（Q1/Q3）
2. **跨境对比**: 对比 A 股 vs 港股 vs 美股的年报结构
3. **时序分析**: 追踪 2015-2025 年报结构演变

---

## 九、关键数据摘要

### 9.1 融合结果分布
```
source                  count   percentage
--------------------------------------------------
md                      34,060  92.3%
pdf_replace             2,163   5.9%
pdf_replace_review      254     0.7%
pdf_low_conf            241     0.7%
unrepairable            181     0.5%
--------------------------------------------------
total                   36,899  100%
```

### 9.2 故障树归因
```
category            count   percentage
------------------------------------------
版式异常            290     38.1%
算法边界            276     36.2%
数据缺失            181     23.8%
跨源冲突            15      2.0%
------------------------------------------
total               762     100%
```

### 9.3 质量指标
```
metric                      value       95% CI
------------------------------------------------------
法规符合率                  0.9864      [0.9856, 0.9872]
跨管线一致性                0.8296      [0.8236, 0.8351]
numbering 准确率            0.9917      -
bookmark 准确率             0.4373      -
font_fallback 准确率        0.5800      -
```

---

## 十、快速恢复指南

### 10.1 查看当前状态
```bash
# 连接 pro 主机
ssh pro

# 查看阶段 3 状态（已暂停）
tmux attach -t stage3

# 查看数据库
psql -h pg.pro.neuralj.com -U travis -d nooshare_dev
\dt annual_semi.*
SELECT source, COUNT(*) FROM annual_semi.h1_fused_result GROUP BY source;
```

### 10.2 重跑关键步骤
```bash
# 重跑融合落地
cd /source/annual-semi
uv run scripts/stage_landing.py

# 重跑不确定性报告
uv run scripts/stage_uncertainty.py

# 重跑故障树
uv run scripts/stage_fault_tree.py
```

### 10.3 导出结果
```bash
# 导出 CSV
psql -h pg.pro.neuralj.com -U travis -d nooshare_dev -c \
  "COPY annual_semi.h1_fused_result TO STDOUT WITH CSV HEADER" > data/h1_fused_result.csv

# 导出 JSONL
uv run scripts/export_jsonl.py
```

---

## 附录 A：关键代码片段

### A.1 法规基准匹配
```python
def legal_rate(headings):
    """计算标题列表与法规基准的匹配率"""
    if not headings:
        return 0.0
    matched = sum(1 for h in headings if h in LEGAL_10 or _canon_match(h, CANON_SET))
    return matched / len(LEGAL_10)
```

### A.2 决策逻辑
```python
def decide_source(md_complete, pdf_available, pdf_quality):
    """决定使用哪个数据源"""
    if md_complete:
        return 'md', 'high'
    if not pdf_available:
        return 'unrepairable', 'low'
    if pdf_quality >= 0.8:
        return 'pdf_replace', 'high'
    if pdf_quality >= 0.6:
        return 'pdf_replace_review', 'medium'
    return 'pdf_low_conf', 'low'
```

### A.3 超时熔断
```python
import signal

def extract_with_timeout(pdf_path, timeout=90):
    """带超时的 PDF 抽取"""
    def handler(signum, frame):
        raise TimeoutError(f"PDF extraction timed out after {timeout}s")
    
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)
    try:
        result = extract_pdf(pdf_path)
        signal.alarm(0)  # 取消闹钟
        return result
    except TimeoutError:
        return {'status': 'timeout', 'headings': []}
```

---

**文档结束**
