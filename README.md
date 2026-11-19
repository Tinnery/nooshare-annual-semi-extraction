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
