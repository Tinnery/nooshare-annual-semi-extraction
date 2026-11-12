"""CLI 入口（骨架，按 R'0-R'9 逐步填充）。"""

import logging

import typer

from annual_semi_extraction.config import LOG_LEVEL

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="A 股年报/半年报 MD 内容抽取与特征矩阵生产。")


@app.command()
def chapter(code: str = typer.Option(..., help="股票代码"), year: int = typer.Option(..., help="报告年份")):
    """R'1: 章节合规检查（§2 号准则当年版本）——待实现。"""
    typer.echo(f"chapter compliance for {code}_{year}: TODO (R'1)")


@app.command()
def extract(code: str = typer.Option(...), year: int = typer.Option(...), period: int = typer.Option(...)):
    """R'2-R'5: 句子级 + 情感 + 表格 + forward-looking 特征抽取——待实现。"""
    typer.echo(f"extract features for {code}_{year}_{period}: TODO (R'2-R'5)")


@app.command()
def matrix(year: int = typer.Option(...), period: int = typer.Option(...)):
    """R'6: 产出特征矩阵（四元 hash 锚）——待实现。"""
    typer.echo(f"build matrix {year}_{period}: TODO (R'6)")


if __name__ == "__main__":
    app()
