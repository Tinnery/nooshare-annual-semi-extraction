"""CLI 入口。

四个命令：
- h1-extract: 批量抽取 H1 一级章节标题
- h1-extract-single: 单文件 H1 抽取
- e1-spec: E1 法规章节合规判定
- version: 版本信息
"""

import json
import logging
from pathlib import Path
from typing import Optional

import typer

from annual_semi_extraction.config import LOG_LEVEL
from annual_semi_extraction.h1.extractor import extract, extract_batch
from annual_semi_extraction.e1.judge import E1Judge
from annual_semi_extraction.spec.loader import SpecLoader

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="A 股年报/半年报结构化抽取与法规合规判定（E1）。")


@app.command()
def h1_extract(
    input_dir: Path = typer.Option(
        ...,
        "--input-dir", "-i",
        help="输入目录（包含 MD 文件的目录，将递归扫描）",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    output: Path = typer.Option(
        "h1_extraction.jsonl",
        "--output", "-o",
        help="输出 JSONL 文件路径",
    ),
    failures: Path = typer.Option(
        "h1_extraction_failures.jsonl",
        "--failures", "-f",
        help="失败/残差记录输出路径",
    ),
    limit: int = typer.Option(
        0,
        "--limit", "-l",
        help="限制处理文件数（0=不限制，调试用）",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        help="跳过前 N 个文件（断点续传用）",
    ),
    append: bool = typer.Option(
        False,
        "--append", "-a",
        help="追加模式（不覆盖已有文件）",
    ),
):
    """H1 标题全量抽取：扫描 input_dir 下所有 MD 文件，抽取 H1 标题并写入 JSONL。

    输入：本地 MD 文件目录（递归扫描）
    输出：每行一个 JSON 对象，包含 slot_key、headings、extraction_method 等字段。
    """
    # 诊断：确认 pattern library 是否加载成功（Run #87 根因：PG_HOST 未传导致静默降级）
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    _m = get_pattern_matcher()
    logger.info(
        f"pattern_library: available={_m.is_available}, "
        f"size={_m.size}, titles={_m.title_count}, "
        f"error={_m.load_error!r}"
    )

    logger.info(f"H1 抽取: input={input_dir}, output={output}")
    result = extract_batch(input_dir, output, failures,
                           limit=limit, offset=offset,
                           append=append)
    n_ok = result["n_ok"]
    n_files = result["n_files"]
    complete = result["complete"]
    residual = result["residual"]
    n_spec_applicable = result["n_spec_applicable"]
    n_spec_not_applicable = result["n_spec_not_applicable"]
    n_spec_unresolved = result["n_spec_unresolved"]
    n_coverage_evaluated = result["n_coverage_evaluated"]
    n_coverage_unavailable = result["n_coverage_unavailable"]
    n_low_heading_sets = result["n_low_heading_sets"]
    logger.info(
        f"完成: {n_ok}/{n_files} 份, "
        f"法规适用: {n_spec_applicable}, 不适用: {n_spec_not_applicable}, "
        f"版本未解析: {n_spec_unresolved}, "
        f"覆盖率可评估: {n_coverage_evaluated}, 映射不可用: {n_coverage_unavailable}, "
        f"完整 L1: {complete}/{n_coverage_evaluated} "
        f"({complete/max(1,n_coverage_evaluated):.1%}), "
        f"残差: {residual}, 低标题数: {n_low_heading_sets}, "
        f"无标题: {result['n_without_headings']}, "
        f"抽取异常: {result['n_extraction_errors']}"
    )
    typer.echo(f"-> {output}")


@app.command()
def h1_extract_single(
    md_path: Path = typer.Argument(..., help="单个 MD 文件路径", exists=True),
):
    """H1 标题单文件抽取：输出 JSON 到 stdout。"""
    rec = extract(md_path)
    if rec is None:
        typer.echo("无有效 H1 标题", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(rec, ensure_ascii=False, indent=2))


@app.command()
def e1_spec(
    slot_key: str = typer.Argument(..., help="报告标识符，格式: {stock_code}_{report_year}_{period}"),
    chapters: list[str] = typer.Argument(..., help="披露的章节标题列表"),
) -> None:
    """E1 法规章节合规判定。

    slot_key 格式: {stock_code}_{report_year}_{period}
    - stock_code: 6 位股票代码
    - report_year: 4 位年份
    - period: 2=半年报, 4=年报

    示例:
    $ annual-semi e1-spec 000001_2024_4 \\
        "第一节 重要提示、目录和释义" \\
        "第二节 公司简介和主要财务指标"
    """
    import re
    
    # 解析 slot_key
    m = re.match(r"^(\d{6})_(\d{4})_([24])$", slot_key)
    if not m:
        typer.echo(f"错误: slot_key 格式不正确: {slot_key}", err=True)
        raise typer.Exit(code=1)
    
    code, year_s, period_s = m.groups()
    year, period = int(year_s), int(period_s)
    
    # 加载规格和判定
    spec = SpecLoader()
    judge = E1Judge(spec)
    verdict = judge.judge(slot_key, period, year, list(chapters))
    
    # 转换为可序列化的字典
    result = {
        "report_id": verdict.report_id,
        "standard": verdict.standard,
        "version": verdict.version,
        "effective_from": verdict.effective_from,
        "required_chapters": verdict.required_chapters,
        "disclosed_chapters": verdict.disclosed_chapters,
        "missing": verdict.missing,
        "not_applicable": verdict.not_applicable,
        "extraction_failures": verdict.extraction_failures,
        "order_violations": [list(v) for v in verdict.order_violations],
        "extra_chapters": verdict.extra_chapters,
        "is_compliant": verdict.is_compliant,
        "compliance_rate": verdict.compliance_rate,
    }
    
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def version() -> None:
    """显示版本信息。"""
    from annual_semi_extraction import __version__
    typer.echo(f"annual-semi-extraction {__version__}")


if __name__ == "__main__":
    app()
