#!/usr/bin/env python3
"""Validate that every H1 output row corresponds byte-for-byte to one downloaded MD."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path, key_field: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            key = record.get(key_field)
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path}:{line_no}: missing {key_field}")
            if key in rows:
                raise ValueError(f"{path}:{line_no}: duplicate {key_field}={key}")
            rows[key] = record
    return rows


def validate(manifest_path: Path, extraction_path: Path) -> dict[str, Any]:
    manifest = read_jsonl(manifest_path, "slot_key")
    extraction = read_jsonl(extraction_path, "slot_key")

    manifest_keys = set(manifest)
    extraction_keys = set(extraction)
    missing = sorted(manifest_keys - extraction_keys)
    extra = sorted(extraction_keys - manifest_keys)

    hash_mismatches: list[str] = []
    missing_manifest_hash: list[str] = []
    missing_extraction_hash: list[str] = []
    for slot_key in sorted(manifest_keys & extraction_keys):
        expected_hash = manifest[slot_key].get("sha256")
        actual_hash = extraction[slot_key].get("source_sha256")
        if not expected_hash:
            missing_manifest_hash.append(slot_key)
        if not actual_hash:
            missing_extraction_hash.append(slot_key)
        if expected_hash and actual_hash and expected_hash != actual_hash:
            hash_mismatches.append(slot_key)

    passed = not (
        missing or extra or hash_mismatches
        or missing_manifest_hash or missing_extraction_hash
    )
    return {
        "manifest_records": len(manifest),
        "extraction_records": len(extraction),
        "missing_extraction_records": len(missing),
        "extra_extraction_records": len(extra),
        "hash_mismatch_records": len(hash_mismatches),
        "missing_manifest_sha256": len(missing_manifest_hash),
        "missing_extraction_sha256": len(missing_extraction_hash),
        "missing_examples": missing[:20],
        "extra_examples": extra[:20],
        "hash_mismatch_examples": hash_mismatches[:20],
        "status": "PASS" if passed else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate(args.manifest, args.extraction)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "H1_INPUT_VALIDATION="
        + result["status"]
        + f" manifest={result['manifest_records']}"
        + f" extracted={result['extraction_records']}"
        + f" hash_mismatches={result['hash_mismatch_records']}"
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
