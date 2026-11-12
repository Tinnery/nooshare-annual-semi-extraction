"""CLI 冒烟测试。"""

from typer.testing import CliRunner

from annual_semi_extraction.cli import app

runner = CliRunner()


def test_cli_help():
    """Validate CLI help is accessible."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "A 股年报/半年报 MD 内容抽取与特征矩阵生产" in result.output


def test_cli_chapter_command_exists():
    """Validate chapter command is registered."""
    result = runner.invoke(app, ["chapter", "--help"])
    assert result.exit_code == 0
    assert "章节合规检查" in result.output


def test_cli_extract_command_exists():
    """Validate extract command is registered."""
    result = runner.invoke(app, ["extract", "--help"])
    assert result.exit_code == 0
    assert "句子级" in result.output


def test_cli_matrix_command_exists():
    """Validate matrix command is registered."""
    result = runner.invoke(app, ["matrix", "--help"])
    assert result.exit_code == 0
    assert "特征矩阵" in result.output
