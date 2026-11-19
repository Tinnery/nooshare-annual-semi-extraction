"""Regression tests for the resumable H1 corpus runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_full_runner_has_no_escaped_continuation_lines() -> None:
    runner = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "run_h1_corpus_full.sh"
    lines = runner.read_text(encoding="utf-8").splitlines()

    malformed = [
        number
        for number, line in enumerate(lines, start=1)
        if line.endswith("\\\\")
    ]

    assert malformed == [], f"double-backslash line continuations at lines {malformed}"


def test_full_runner_stops_after_two_committed_batches_at_process_limit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    ci_dir = project / "scripts" / "ci"
    ci_dir.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "ci" / "run_h1_corpus_full.sh",
        ci_dir / "run_h1_corpus_full.sh",
    )

    write_executable(ci_dir / "build_stunnel.sh", "#!/usr/bin/env bash\nexit 0\n")
    write_executable(ci_dir / "teardown.sh", "#!/usr/bin/env bash\nexit 0\n")
    write_executable(ci_dir / "leak_check.sh", "#!/usr/bin/env bash\nexit 0\n")

    fake_bin = tmp_path / "bin"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    fake_uv = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
runner_temp = Path(os.environ["RUNNER_TEMP"])


def option(name):
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        raise SystemExit(2)


if "h1_corpus_download.py" in args:
    state = runner_temp / "download-count"
    batch = int(state.read_text() if state.exists() else "0") + 1
    state.write_text(str(batch), encoding="utf-8")

    output = Path(os.environ["CORPUS_OUTPUT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    first_year = 2000 + (batch - 1) * 10
    rows = []
    keys = []
    for offset in range(10):
        year = first_year + offset
        slot_key = f"000001_{year}_2"
        key = f"published/000001/{slot_key}.md"
        rows.append({
            "path": str(output / key),
            "s3_key": key,
            "slot_key": slot_key,
            "sha256": f"{year + 1:064x}",
            "size": 1,
        })
        keys.append(key)

    (output / "input-manifest.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (output / "batch-summary.json").write_text(
        json.dumps({
            "n_enumerated": 10,
            "n_downloaded": 10,
            "last_key": keys[-1],
            "end_of_corpus": False,
            "total_bytes": 10,
        }),
        encoding="utf-8",
    )
    print("CORPUS_DOWNLOAD=PASS")
    raise SystemExit(0)

if "h1-extract" in args:
    output = Path(option("--output"))
    failures = Path(option("--failures"))
    manifest = Path(os.environ["CORPUS_OUTPUT_DIR"]) / "input-manifest.jsonl"
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    extracted = [
        {"slot_key": row["slot_key"], "source_sha256": row["sha256"], "headings": []}
        for row in rows
    ]
    output.write_text(
        "".join(json.dumps(row) + "\n" for row in extracted), encoding="utf-8"
    )
    failures.write_text("", encoding="utf-8")
    print("H1_EXTRACT=PASS")
    raise SystemExit(0)

if "validate_h1_batch.py" in args:
    required = ("--manifest", "--extraction", "--output")
    if not all(name in args for name in required):
        print("VALIDATION_ARGUMENTS_MISSING", file=sys.stderr)
        raise SystemExit(2)
    manifest = Path(option("--manifest"))
    extraction = Path(option("--extraction"))
    output = Path(option("--output"))
    if not manifest.is_file() or not extraction.is_file():
        raise SystemExit(2)
    calls = runner_temp / "validation-calls"
    with calls.open("a", encoding="utf-8") as stream:
        stream.write("validated\n")
    output.write_text(json.dumps({"status": "PASS", "hash_mismatch_records": 0}), encoding="utf-8")
    print("H1_BATCH_INPUT_VALIDATION=PASS")
    raise SystemExit(0)

if "h1_corpus_load_pg.py" in args and "--emit-sql" in args:
    output = Path(option("--emit-sql"))
    output.write_text("BEGIN;\nCOMMIT;\n", encoding="utf-8")
    print("SQL_EMIT=PASS")
    raise SystemExit(0)

if "summarize_h1_corpus.py" in args:
    output = Path(option("--output"))
    output.write_text(json.dumps({"accounting_status": "PASS"}), encoding="utf-8")
    print("H1_ACCOUNTING_SUMMARY=PASS")
    raise SystemExit(0)

print("UNEXPECTED_UV_INVOCATION", args, file=sys.stderr)
raise SystemExit(97)
"""
    write_executable(fake_bin / "uv", fake_uv)

    fake_psql = r"""#!/usr/bin/env python3
import os
from pathlib import Path

calls = Path(os.environ["RUNNER_TEMP"]) / "pg-calls"
with calls.open("a", encoding="utf-8") as stream:
    stream.write("committed\n")
"""
    write_executable(fake_bin / "psql", fake_psql)
    write_executable(fake_bin / "nc", "#!/usr/bin/env bash\nexit 1\n")
    write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update({
        "PATH": str(fake_bin) + os.pathsep + env.get("PATH", ""),
        "RUNNER_TEMP": str(runner_temp),
        "H1_CORPUS_BATCH_SIZE": "10",
        "H1_EXPECTED_CORPUS_COUNT": "20",
        "H1_PROCESSED_BEFORE": "0",
        "H1_PROCESS_LIMIT": "20",
        "CORPUS_START_AFTER": "",
    })

    result = subprocess.run(
        ["bash", "scripts/ci/run_h1_corpus_full.sh"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert result.stdout.count("H1_BATCH_DONE") == 2
    assert result.stdout.count("PG_BATCH_LOAD=PASS") == 2
    assert "H1_PROCESS_LIMIT_REACHED count=20" in result.stdout
    assert "H1_FULL_SUMMARY written batches=2 downloaded=20 extracted=20 pg_loaded=20" in result.stdout

    checkpoint = json.loads((project / "h1-corpus-checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["batch_no"] == 2
    assert checkpoint["downloaded"] == 20
    assert checkpoint["extracted"] == 20
    assert checkpoint["pg_loaded"] == 20
    assert checkpoint["last_key"] == "published/000001/000001_2019_2.md"

    assert (runner_temp / "validation-calls").read_text(encoding="utf-8").splitlines() == [
        "validated",
        "validated",
    ]
    assert (runner_temp / "pg-calls").read_text(encoding="utf-8").splitlines() == [
        "committed",
        "committed",
    ]
