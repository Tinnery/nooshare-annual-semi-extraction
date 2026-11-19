"""Tests for preserving H1 nullable coverage fields in PostgreSQL writes."""
from scripts.ci.h1_corpus_load_pg import build_sql, int_array_literal


def test_integer_array_literal_distinguishes_null_from_empty() -> None:
    assert int_array_literal(None) == "NULL::integer[]"
    assert int_array_literal([]) == "ARRAY[]::integer[]"
    assert int_array_literal([1, 3]) == "'{1,3}'::integer[]"


def test_build_sql_keeps_unresolved_missing_sections_null() -> None:
    sql = build_sql([{
        "slot_key": "000001_2006_2",
        "stock_code": "000001",
        "report_year": 2006,
        "period": 2,
        "source_sha256": "a" * 64,
        "n_bytes": 123,
        "extraction_method": "ch_zh",
        "n_headings": 3,
        "ordinal_valid": True,
        "ordinal_verdict": "PASS",
        "is_complete_l1": None,
        "coverage_ratio": None,
        "headings": [],
        "missing_always_sections": None,
        "missing_conditional_sections": None,
        "reg_version": None,
    }])

    assert "NULL::integer[]" in sql
    assert "ARRAY[]::integer[]" not in sql
