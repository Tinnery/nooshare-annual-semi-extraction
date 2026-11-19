# nooshare-annual-semi-extraction

A 股年报/半年报结构化内容抽取与法规合规判定（E1）。

## 功能

- **H1 章节抽取**：从年报/半年报 MD 文件中批量抽取一级章节标题
- **E1 法规判定**：基于法规规格文件包（E1-E6 判定框架）判定章节合规性
- **模式匹配**：支持 H1 标题的形态学分析、编号规范化与模式匹配

## 安装

```bash
uv sync
```

## 使用

```bash
# 批量抽取 H1 章节
uv run nooshare-annual-semi-extraction h1-extract --input-dir <目录> --output <输出文件>

# 单文件抽取
uv run nooshare-annual-semi-extraction h1-extract-single <文件>

# E1 法规合规判定
uv run nooshare-annual-semi-extraction e1-spec --input <文件>

# 查看版本
uv run nooshare-annual-semi-extraction version
```

## 项目结构

```
annual_semi_extraction/
├── cli.py              # CLI 入口
├── config.py           # 配置
├── h1/                 # H1 章节抽取
│   ├── extractor.py    # 抽取器
│   ├── morphology.py   # 形态学分析
│   ├── normalizer.py   # 编号规范化
│   ├── numbering.py    # 编号处理
│   └── pattern_matcher.py  # 模式匹配
├── e1/                 # E1 法规判定
│   └── judge.py        # 判定器
└── spec/               # 规格文件加载
    └── loader.py       # 加载器
```

## 依赖

- Python 3.11+
- typer（CLI）
- psycopg2-binary（模板库读取）

## 相关仓库

- `nooshare-annual-semi`：年报/半年报 MD 语料（已封版）
- `nooshare-specs`：法规规格文件包（E1-E6 判定框架）

## CI 工作流

### h1-corpus job

独立的 H1 语料批量生产流程，从 RustFS annual-semi 桶下载已发布的 MD 文件，执行 H1 标题抽取，并将结果写入 PG 数据库。

**职责边界**：
- 只消费已发布的语料（`published/` 前缀）
- 不执行上游 MD 完整性检查
- 产出写入 `annual_semi.h1_corpus_results` 表

**与 infra-probe 的区别**：
- `infra-probe`：验证基础设施连通性（canary 往返）
- `h1-corpus`：生产研究数据（批量读取 + 抽取 + PG 写入）

**PG 表结构**（`annual_semi.h1_corpus_results`）：
- `slot_key` (PK): 语料槽位键（如 `000001_2003_2`）
- `stock_code`, `report_year`, `period`: 股票/年份/报告期
- `source_sha256`, `n_bytes`: 源文件校验
- `extraction_method`, `n_headings`: 抽取方法/标题数
- `ordinal_valid`, `ordinal_verdict`: 序号校验
- `is_complete_l1`, `coverage_ratio`: 结构完整性
- `headings_json` (JSONB): 标题详情
- `missing_always_sections`, `missing_conditional_sections`: 缺失章节
- `loaded_at`: 加载时间戳

**Artifact 内容**（保留 MD 用于校验）：
- `corpus-data/`: 下载的 MD 文件 + input-manifest.jsonl
- `h1-extraction.jsonl`: H1 抽取结果
- `h1-extraction-failures.jsonl`: 覆盖率检查失败记录
- `h1-corpus-summary.json`: 批次摘要（含 PG 写入统计）
