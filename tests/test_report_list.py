"""报告列表模块单测：SQL 构造、行解析、不连 PG 的纯逻辑。"""
from annual_semi_extraction.report_list import (
    VALID_PERIODS,
    build_query,
    slot_from_row,
)


def test_build_query_filters_year_and_period():
    sql = build_query(2019)
    assert "annual_semi.reconciled_report" in sql
    assert "report_year >= 2019" in sql
    assert "period IN (2,4)" in sql
    assert sql.strip().upper().startswith("SELECT")


def test_build_query_respects_custom_start_year():
    sql = build_query(2022)
    assert "report_year >= 2022" in sql
    assert "report_year >= 2019" not in sql


def test_slot_from_row_standard():
    slot = slot_from_row("000001|2023|4|published/000001/000001_2023_4.md")
    assert slot is not None
    assert slot.slot_key == "000001_2023_4"
    assert slot.s3_key == "published/000001/000001_2023_4.md"
    assert slot.stock_code == "000001"
    assert slot.report_year == 2023
    assert slot.period == 4
    assert slot.winner_md_path == "published/000001/000001_2023_4.md"


def test_slot_from_row_path_with_pipe():
    slot = slot_from_row("300960|2024|2|structured/provider/a|b.md")
    assert slot is not None
    assert slot.winner_md_path == "structured/provider/a|b.md"
    assert slot.s3_key == "published/300960/300960_2024_2.md"


def test_slot_from_row_rejects_malformed():
    assert slot_from_row("bad") is None
    assert slot_from_row("000001|abcd|4|p") is None
    assert slot_from_row("000001|2023|9|p") is None  # period 非法
    assert slot_from_row("|2023|4|p") is None


def test_valid_periods_only_annual_and_semi():
    assert VALID_PERIODS == (2, 4)


def test_to_dict_shape():
    slot = slot_from_row("000001|2023|4|published/x.md")
    d = slot.to_dict()
    assert set(d.keys()) == {
        "slot_key", "s3_key", "stock_code", "report_year", "period", "winner_md_path"
    }
