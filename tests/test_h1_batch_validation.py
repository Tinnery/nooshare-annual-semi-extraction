"""Tests for H1 batch input/output identity verification."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.validate_h1_batch import validate


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_validate_accepts_matching_slots_and_hashes(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    extraction = tmp_path / "h1.jsonl"
    write_jsonl(manifest, [
        {"slot_key": "000001_2023_4", "sha256": "a" * 64},
        {"slot_key": "000002_2023_2", "sha256": "b" * 64},
    ])
    write_jsonl(extraction, [
        {"slot_key": "000001_2023_4", "source_sha256": "a" * 64},
        {"slot_key": "000002_2023_2", "source_sha256": "b" * 64},
    ])

    result = validate(manifest, extraction)

    assert result["status"] == "PASS"
    assert result["manifest_records"] == 2
    assert result["extraction_records"] == 2
    assert result["hash_mismatch_records"] == 0


def test_validate_rejects_same_count_with_wrong_source_hash(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    extraction = tmp_path / "h1.jsonl"
    write_jsonl(manifest, [
        {"slot_key": "000001_2023_4", "sha256": "a" * 64},
    ])
    write_jsonl(extraction, [
        {"slot_key": "000001_2023_4", "source_sha256": "c" * 64},
    ])

    result = validate(manifest, extraction)

    assert result["status"] == "FAIL"
    assert result["hash_mismatch_records"] == 1
    assert result["hash_mismatch_examples"] == ["000001_2023_4"]


def test_validate_rejects_missing_and_extra_rows(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    extraction = tmp_path / "h1.jsonl"
    write_jsonl(manifest, [
        {"slot_key": "000001_2023_4", "sha256": "a" * 64},
        {"slot_key": "000002_2023_2", "sha256": "b" * 64},
    ])
    write_jsonl(extraction, [
        {"slot_key": "000001_2023_4", "source_sha256": "a" * 64},
        {"slot_key": "000003_2023_2", "source_sha256": "d" * 64},
    ])

    result = validate(manifest, extraction)

    assert result["status"] == "FAIL"
    assert result["missing_extraction_records"] == 1
    assert result["extra_extraction_records"] == 1


def test_validate_rejects_duplicate_slot_keys(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    extraction = tmp_path / "h1.jsonl"
    write_jsonl(manifest, [
        {"slot_key": "000001_2023_4", "sha256": "a" * 64},
        {"slot_key": "000001_2023_4", "sha256": "a" * 64},
    ])
    write_jsonl(extraction, [])

    with pytest.raises(ValueError, match="duplicate slot_key"):
        validate(manifest, extraction)
