#!/usr/bin/env bash
# PG 只读读取探针（经 stunnel）。分阶段检查结果集，最终完整读取仅驻留在 Runner 临时目录。
# 公开仓库不上传原始表数据；日志只记录数量、传输字节数和 SHA-256。
set -uo pipefail

AUDIT="${RUNNER_TEMP:-/tmp}/ci_audit.log"
WORK_DIR="${RUNNER_TEMP:-/tmp}"
PG_HOST="127.0.0.1"
PG_PORT="${PG_LOCAL_PORT:-15432}"
PG_DB="nooshare_dev"
PG_USER="ci_probe"
STAGE_DIR="$WORK_DIR/pg-read-diagnostics"
SQL_FILE="$WORK_DIR/pg-read-diagnostics.sql"
CONTROL_LOG="$WORK_DIR/pg-read-control.log"
EXPORT_ERR="$WORK_DIR/pg-read-error.log"
EXPORT_OUT="$WORK_DIR/h1_pattern_library.csv"

cleanup() {
  rm -rf "$STAGE_DIR"
  rm -f "$SQL_FILE" "$CONTROL_LOG" "$EXPORT_ERR" "$EXPORT_OUT"
}
trap cleanup EXIT

if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_PROBE=FAIL code=PG_SECRET_MISSING" | tee -a "$AUDIT"
  exit 1
fi

rm -rf "$STAGE_DIR"
mkdir -m 700 -p "$STAGE_DIR"
rm -f "$SQL_FILE" "$CONTROL_LOG" "$EXPORT_ERR" "$EXPORT_OUT"

# All stages use one psql process, one PostgreSQL session, and one repeatable-read snapshot.
# Result sets stay in runner.temp and are deleted when this script exits.
cat > "$SQL_FILE" <<SQL
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
\echo STAGE=summary
\o $STAGE_DIR/summary.csv
SELECT current_setting('server_version') AS server_version,
       count(*) AS row_count,
       sum(pg_column_size(t)) AS payload_bytes,
       max(pg_column_size(t)) AS max_row_bytes
FROM annual_semi.h1_pattern_library AS t;
\o
\echo STAGE=key_sample
\o $STAGE_DIR/key_sample.csv
SELECT pattern_hash
FROM annual_semi.h1_pattern_library
ORDER BY pattern_hash
LIMIT 1;
\o
\echo STAGE=full_row_sample
\o $STAGE_DIR/full_row_sample.csv
SELECT *
FROM annual_semi.h1_pattern_library
ORDER BY pattern_hash
LIMIT 1;
\o
\echo STAGE=ten_rows
\o $STAGE_DIR/ten_rows.csv
SELECT *
FROM annual_semi.h1_pattern_library
ORDER BY pattern_hash
LIMIT 10;
\o
\echo STAGE=full_export
\o $EXPORT_OUT
SELECT *
FROM annual_semi.h1_pattern_library
ORDER BY pattern_hash;
\o
COMMIT;
SQL
chmod 600 "$SQL_FILE"

if PGPASSWORD="$PG_PASSWORD" psql \
    -X --csv -v ON_ERROR_STOP=1 \
    -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    -f "$SQL_FILE" > "$CONTROL_LOG" 2> "$EXPORT_ERR"; then
  python3 - "$STAGE_DIR" "$EXPORT_OUT" <<'PY'
import csv
import hashlib
import pathlib
import sys

stage_dir = pathlib.Path(sys.argv[1])
export_path = pathlib.Path(sys.argv[2])

def read_rows(path: pathlib.Path):
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)

summary_fields, summary_rows = read_rows(stage_dir / 'summary.csv')
key_fields, key_rows = read_rows(stage_dir / 'key_sample.csv')
row_fields, row_rows = read_rows(stage_dir / 'full_row_sample.csv')
ten_fields, ten_rows = read_rows(stage_dir / 'ten_rows.csv')
full_fields, full_rows = read_rows(export_path)

if len(summary_rows) != 1 or len(key_rows) != 1 or len(row_rows) != 1:
    raise SystemExit("PG_RESULT_VALIDATION_FAILED")
if len(ten_rows) != 10 or len(full_rows) != int(summary_rows[0]['row_count']):
    raise SystemExit("PG_RESULT_VALIDATION_FAILED")
if not full_rows:
    raise SystemExit("PG_RESULT_EMPTY")
if not {'server_version', 'row_count', 'payload_bytes', 'max_row_bytes'}.issubset(summary_fields):
    raise SystemExit("PG_RESULT_SCHEMA_FAILED")
expected = {'pattern_hash', 'pattern', 'count', 'headings'}
if not expected.issubset(full_fields) or not expected.issubset(row_fields):
    raise SystemExit("PG_RESULT_SCHEMA_FAILED")

summary = summary_rows[0]
if not export_path.is_file() or export_path.stat().st_size <= 0:
    raise SystemExit("PG_RESULT_EMPTY")

digest = hashlib.sha256(export_path.read_bytes()).hexdigest()
print(
    "PG_PROBE=PASS "
    f"version={summary['server_version']} patterns={len(full_rows)}"
)
print(
    "PG_READ_PROBE=PASS "
    f"key_sample={len(key_rows)} full_row_sample={len(row_rows)} "
    f"rows_10={len(ten_rows)} rows_full={len(full_rows)} "
    f"payload_bytes={summary['payload_bytes']} "
    f"max_row_bytes={summary['max_row_bytes']} "
    f"csv_bytes={export_path.stat().st_size} sha256={digest}"
)
PY
  result=$?
  if [ "$result" -ne 0 ]; then
    echo "PG_PROBE=FAIL code=PG_RESULT_VALIDATION" | tee -a "$AUDIT"
  fi
else
  stage="$(grep -oE 'STAGE=[A-Za-z0-9_]+' "$CONTROL_LOG" 2>/dev/null | tail -1 | cut -d= -f2)"
  stage="${stage:-unknown}"
  code="PG_READ_QUERY_FAILED"
  if grep -qi "permission denied" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_PERMISSION_DENIED"
  elif grep -qiE "server closed the connection|unexpected eof|connection reset by peer|SSL SYSCALL error.*EOF|could not receive data from server|connection terminated unexpectedly" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_TUNNEL_DROP"
  elif grep -qiE "statement timeout|canceling statement" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_STATEMENT_TIMEOUT"
  elif grep -qiE "could not connect to server|timeout|timed out" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_TIMEOUT"
  elif grep -qi "no pg_hba.conf entry" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_HBA_DENY"
  elif grep -qi "does not exist" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_READ_OBJECT_MISSING"
  fi
  echo "PG_PROBE=FAIL stage=$stage code=$code" | tee -a "$AUDIT"
  result=1
fi

exit "$result"
