#!/usr/bin/env python3
"""导出权威报告列表为 JSONL，供 h1_corpus_download.py 作为白名单消费。

数据源：annual_semi.reconciled_report（nooshare-annual-semi 的裁决真相源）
过滤：report_year >= start_year（默认 2019），period in (2,4)
连接：psql 子进程（CI stunnel 隧道），只读角色 ci。

输出：
    {output}/report-list.jsonl        每行一个 ReportSlot
    {output}/report-list-summary.json 统计摘要

审计行（stdout，供 leak_check 校验）：
    REPORT_LIST=PASS n=<count> start_year=<year> min_year=<y> max_year=<y>
    REPORT_LIST=FAIL code=<固定错误码>

安全：异常只映射为固定错误码，绝不回显异常对象/连接串/凭据线索。
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from annual_semi_extraction.report_list import load_report_list_from_env


def audit(line: str) -> None:
    print(line)
    try:
        work_dir = os.environ.get("RUNNER_TEMP", "/tmp")
        with open(os.path.join(work_dir, "ci_audit.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main() -> None:
    try:
        start_year = int(os.environ.get("H1_START_YEAR", "2019"))
    except ValueError:
        audit("REPORT_LIST=FAIL code=INVALID_START_YEAR")
        sys.exit(1)

    output_dir = os.environ.get("CORPUS_OUTPUT_DIR", "corpus-data")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    slots, err = load_report_list_from_env(start_year)
    if err:
        audit(f"REPORT_LIST=FAIL code={err}")
        sys.exit(1)
    assert slots is not None
    if not slots:
        audit("REPORT_LIST=FAIL code=EMPTY_REPORT_LIST")
        sys.exit(1)

    list_path = out_path / "report-list.jsonl"
    years: list[int] = []
    semi_count = 0
    annual_count = 0
    with list_path.open("w", encoding="utf-8") as f:
        for slot in slots:
            f.write(json.dumps(slot.to_dict(), ensure_ascii=False) + "\n")
            years.append(slot.report_year)
            if slot.period == 4:
                annual_count += 1
            else:
                semi_count += 1

    summary = {
        "source_table": "annual_semi.reconciled_report",
        "start_year": start_year,
        "n_slots": len(slots),
        "annual_count": annual_count,
        "semi_count": semi_count,
        "report_year_min": min(years),
        "report_year_max": max(years),
        "list_path": str(list_path),
    }
    (out_path / "report-list-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    audit(
        f"REPORT_LIST=PASS n={len(slots)} start_year={start_year} "
        f"min_year={min(years)} max_year={max(years)} "
        f"annual={annual_count} semi={semi_count}"
    )


if __name__ == "__main__":
    main()
