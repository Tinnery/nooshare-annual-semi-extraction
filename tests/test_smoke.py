"""冒烟测试：确认 package 可导入、CLI 可调用。"""


def test_package_import():
    import annual_semi_extraction
    assert annual_semi_extraction.__version__ == "0.1.0"


def test_cli_app_exists():
    from annual_semi_extraction.cli import app
    assert app is not None
