"""CLI 冒烟测试。"""

from typer.testing import CliRunner

from annual_semi_extraction.cli import app

runner = CliRunner()


def test_cli_help():
    """Validate CLI help is accessible."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "A 股年报/半年报 MD 内容抽取与特征矩阵生产" in result.output


def test_cli_h1_extract_command_exists():
    """Validate h1-extract command is registered."""
    result = runner.invoke(app, ["h1-extract", "--help"])
    assert result.exit_code == 0
    assert "H1 标题全量抽取" in result.output


def test_cli_h1_extract_single_command_exists():
    """Validate h1-extract-single command is registered."""
    result = runner.invoke(app, ["h1-extract-single", "--help"])
    assert result.exit_code == 0
    assert "H1 标题单文件抽取" in result.output


def test_cli_e1_spec_command_exists():
    """Validate e1-spec command is registered."""
    result = runner.invoke(app, ["e1-spec", "--help"])
    assert result.exit_code == 0
    assert "法定应披章节" in result.output


def test_cli_version_command_exists():
    """Validate version command is registered."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "nooshare-annual-semi-extraction" in result.output
