#!/usr/bin/env python3
"""Summarize full-run H1 JSONL without loading the corpus into memory."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def count_jsonl(path: Path) -> tuple[int, Counter[str]]:
    counts: Counter[str] = Counter()
    total = 0
    if not path.exists():
        return total, counts
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
            total += 1
            reasons = record.get("reasons")
            if isinstance(reasons, list):
                counts.update(str(reason) for reason in reasons)
            elif record.get("reason"):
                counts[str(record["reason"])] += 1
    return total, counts


def summarize(input_path: Path, failures_path: Path, expected: int) -> dict[str, Any]:
    extraction_methods: Counter[str] = Counter()
    heading_statuses: Counter[str] = Counter()
    ordinal_verdicts: Counter[str] = Counter()
    spec_statuses: Counter[str] = Counter()
    coverage_statuses: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    seen_slots: set[str] = set()
    duplicate_slots: list[str] = []
    n_records = 0
    n_headings = 0
    n_without_sha = 0
    n_spec_applicable = 0
    n_spec_not_applicable = 0
    n_spec_unresolved = 0
    n_coverage_available = 0
    n_coverage_unavailable = 0
    n_complete_l1 = 0
    n_no_headings = 0
    n_low_heading_sets = 0

    with input_path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{input_path}:{line_no}: invalid JSONL: {exc}") from exc

            n_records += 1
            slot_key = record.get("slot_key")
            if not slot_key:
                raise ValueError(f"{input_path}:{line_no}: missing slot_key")
            if slot_key in seen_slots:
                duplicate_slots.append(str(slot_key))
            else:
                seen_slots.add(str(slot_key))

            if not record.get("source_sha256"):
                n_without_sha += 1

            n_headings += int(record.get("n_headings") or 0)
            extraction_methods[str(record.get("extraction_method") or "UNKNOWN")] += 1
            heading_status = str(record.get("heading_set_status") or "UNKNOWN")
            heading_statuses[heading_status] += 1
            ordinal_verdicts[str(record.get("ordinal_verdict") or "UNKNOWN")] += 1
            spec_resolution = str(record.get("spec_resolution_status") or "UNKNOWN")
            spec_statuses[spec_resolution] += 1
            coverage_statuses[str(record.get("coverage_status") or "UNKNOWN")] += 1

            spec_applicable = record.get("spec_applicable")
            if spec_applicable is True:
                n_spec_applicable += 1
            elif spec_applicable is False:
                n_spec_not_applicable += 1
            else:
                n_spec_unresolved += 1

            if record.get("coverage_available") is True:
                n_coverage_available += 1
            else:
                n_coverage_unavailable += 1

            if record.get("is_complete_l1") is True:
                n_complete_l1 += 1
            if int(record.get("n_headings") or 0) == 0:
                n_no_headings += 1
            if heading_status == "LOW_HEADING_COUNT":
                n_low_heading_sets += 1

    n_failures, failure_reasons = count_jsonl(failures_path)
    unique_slots = len(seen_slots)
    count_matches = n_records == expected
    duplicates_clear = not duplicate_slots
    sha_complete = n_without_sha == 0

    return {
        "expected_records": expected,
        "n_records": n_records,
        "n_unique_slots": unique_slots,
        "n_duplicate_slots": len(duplicate_slots),
        "duplicate_slot_examples": duplicate_slots[:20],
        "n_without_source_sha256": n_without_sha,
        "source_hashes_complete": sha_complete,
        "record_count_matches_expected": count_matches,
        "n_headings_total": n_headings,
        "average_headings_per_report": round(n_headings / max(1, n_records), 4),
        "n_failures_or_residuals": n_failures,
        "failure_reason_distribution": dict(failure_reasons),
        "extraction_method_distribution": dict(extraction_methods),
        "heading_set_status_distribution": dict(heading_statuses),
        "ordinal_verdict_distribution": dict(ordinal_verdicts),
        "spec_resolution_distribution": dict(spec_statuses),
        "coverage_status_distribution": dict(coverage_statuses),
        "n_spec_applicable": n_spec_applicable,
        "n_spec_not_applicable": n_spec_not_applicable,
        "n_spec_unresolved": n_spec_unresolved,
        "n_coverage_available": n_coverage_available,
        "n_coverage_unavailable": n_coverage_unavailable,
        "n_complete_l1": n_complete_l1,
        "n_without_headings": n_no_headings,
        "n_low_heading_sets": n_low_heading_sets,
        "acceptance": "PASS" if count_matches and duplicates_clear and sha_complete else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a complete H1 extraction JSONL")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--failures", type=Path, required=True)
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = summarize(args.input, args.failures, args.expected)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "H1_QUALITY_SUMMARY="
        + str(result["acceptance"])
        + f" records={result['n_records']} residuals={result['n_failures_or_residuals']} "
        + f"duplicates={result['n_duplicate_slots']} missing_sha={result['n_without_source_sha256']}"
    )
    if result["acceptance"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
