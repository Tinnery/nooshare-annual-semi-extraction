#!/usr/bin/env bash
# PG 真连探针（经 stunnel 本地端口）。只读验证并导出 H1 Pattern Library。
# 先验证 COUNT 与单行 SELECT，再尝试整表读取；若整表传输失败，按小页串行读取。
# 失败只输出固定错误码，绝不回显原始错误或查询数据。
set -uo pipefail

AUDIT="${RUNNER_TEMP:-/tmp}/ci_audit.log"
WORK_DIR="${RUNNER_TEMP:-/tmp}"
PG_HOST="127.0.0.1"
PG_PORT="${PG_LOCAL_PORT:-15432}"
PG_DB="nooshare_dev"
PG_USER="ci_probe"
EXPORT_OUT="$WORK_DIR/h1_pattern_library.csv"
COUNT_OUT="$WORK_DIR/h1_pattern_library_count.txt"
COUNT_ERR="$WORK_DIR/h1_pattern_library_count_err.txt"
PREVIEW_OUT="$WORK_DIR/h1_pattern_library_preview.csv"
PREVIEW_ERR="$WORK_DIR/h1_pattern_library_preview_err.txt"
EXPORT_ERR="$WORK_DIR/h1_pattern_library_export_err.txt"
CHUNK_DIR="$WORK_DIR/h1_pattern_library_chunks"

cleanup_tmp() {
  rm -f "$COUNT_OUT" "$COUNT_ERR" "$PREVIEW_OUT" "$PREVIEW_ERR" "$EXPORT_ERR"
  rm -rf "$CHUNK_DIR"
}
trap cleanup_tmp EXIT

if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_PROBE=FAIL code=PG_SECRET_MISSING" | tee -a "$AUDIT"
  exit 1
fi

rm -f "$EXPORT_OUT"
mkdir -p "$CHUNK_DIR"

classify_pg_error() {
  local error_file="$1"
  if grep -qi "permission denied" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_PERMISSION_DENIED"
  elif grep -qi "server closed the connection\|unexpected eof\|connection reset by peer\|SSL SYSCALL error: EOF detected\|connection terminated unexpectedly" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_TUNNEL_DROP"
  elif grep -qi "connection refused" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_TCP_REFUSED"
  elif grep -qi "could not connect to server\|timeout\|timed out" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_TIMEOUT"
  elif grep -qi "no pg_hba.conf entry" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_HBA_DENY"
  elif grep -qi "does not exist" "$error_file" 2>/dev/null; then
    echo "PG_EXPORT_OBJECT_MISSING"
  else
    echo "PG_EXPORT_QUERY_FAILED"
  fi
}

run_csv_query() {
  local query="$1"
  local output_file="$2"
  local error_file="$3"
  PGPASSWORD="$PG_PASSWORD" PGCONNECT_TIMEOUT=15 psql \
    -X -q --csv -v ON_ERROR_STOP=1 \
    -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    -c "$query" > "$output_file" 2> "$error_file"
}

validate_csv() {
  local path="$1"
  local expected="$2"
  python3 - "$path" "$expected" <<'PY'
import csv
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
expected = int(sys.argv[2])
required = {"pattern_hash", "pattern", "count", "headings"}

try:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        if not required.issubset(fields):
            raise SystemExit(11)
        rows = sum(1 for _ in reader)
except (OSError, UnicodeError, csv.Error):
    raise SystemExit(12)

if rows != expected:
    raise SystemExit(13)
PY
}

report_csv() {
  local label="$1"
  local path="$2"
  python3 - "$label" "$path" <<'PY'
import csv
import hashlib
import pathlib
import sys

label, name = sys.argv[1], sys.argv[2]
path = pathlib.Path(name)
with path.open("r", encoding="utf-8", newline="") as stream:
    rows = sum(1 for _ in csv.DictReader(stream))
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"{label} rows={rows} bytes={path.stat().st_size} sha256={digest}")
PY
}

# 1) 复核已知可用的基础穿透：服务端版本与表行数。
if PGPASSWORD="$PG_PASSWORD" PGCONNECT_TIMEOUT=15 psql \
    -X -q -A -t -F $'\t' -v ON_ERROR_STOP=1 \
    -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    -c "SELECT current_setting('server_version'), count(*) FROM annual_semi.h1_pattern_library;" \
    > "$COUNT_OUT" 2> "$COUNT_ERR"; then
  IFS=$'\t' read -r version expected_rows < "$COUNT_OUT"
  version="$(printf '%s' "$version" | tr -d '[:space:]')"
  expected_rows="$(printf '%s' "$expected_rows" | tr -d '[:space:]')"
  if [[ ! "$version" =~ ^[0-9]+\.[0-9]+ ]] || [[ ! "$expected_rows" =~ ^[0-9]+$ ]] || [ "$expected_rows" -le 0 ]; then
    echo "PG_PROBE=FAIL code=PG_COUNT_ASSERT" | tee -a "$AUDIT"
    exit 1
  fi
  echo "PG_PROBE=PASS version=$version patterns=$expected_rows" | tee -a "$AUDIT"
else
  code="$(classify_pg_error "$COUNT_ERR")"
  echo "PG_PROBE=FAIL code=$code" | tee -a "$AUDIT"
  exit 1
fi

# 2) 单行 SELECT：区分权限/对象问题与大结果集传输问题。
if run_csv_query \
    "SELECT * FROM annual_semi.h1_pattern_library ORDER BY pattern_hash LIMIT 1;" \
    "$PREVIEW_OUT" "$PREVIEW_ERR" && validate_csv "$PREVIEW_OUT" 1; then
  chmod 600 "$PREVIEW_OUT"
  report_csv "PG_ROW_READ=PASS" "$PREVIEW_OUT"
else
  code="$(classify_pg_error "$PREVIEW_ERR")"
  if [ ! -s "$PREVIEW_ERR" ]; then
    code="PG_EXPORT_SCHEMA_OR_ROW_ASSERT"
  fi
  echo "PG_ROW_READ=FAIL code=$code" | tee -a "$AUDIT"
  rm -f "$EXPORT_OUT"
  exit 1
fi

# 3) 优先尝试单次整表读取。
full_ok=0
if run_csv_query \
    "SELECT * FROM annual_semi.h1_pattern_library ORDER BY pattern_hash;" \
    "$EXPORT_OUT" "$EXPORT_ERR"; then
  if validate_csv "$EXPORT_OUT" "$expected_rows"; then
    full_ok=1
  else
    echo "PG_FULL_EXPORT=FAIL code=PG_EXPORT_ROW_OR_SCHEMA_MISMATCH" | tee -a "$AUDIT"
  fi
else
  code="$(classify_pg_error "$EXPORT_ERR")"
  echo "PG_FULL_EXPORT=FAIL code=$code" | tee -a "$AUDIT"
fi

if [ "$full_ok" -eq 1 ]; then
  chmod 600 "$EXPORT_OUT"
  report_csv "PG_PATTERN_LIBRARY_EXPORT=PASS mode=single-query" "$EXPORT_OUT"
  exit 0
fi

# 4) 整表读取失败时按 10 行分页串行读取，避免并发占用同一 PSK identity 的隧道槽。
chunk_size=10
chunk_paths=()
offset=0
chunk_index=0
while [ "$offset" -lt "$expected_rows" ]; do
  chunk_file="$CHUNK_DIR/chunk_$chunk_index.csv"
  chunk_err="$CHUNK_DIR/chunk_$chunk_index.err"
  query="SELECT * FROM annual_semi.h1_pattern_library ORDER BY pattern_hash LIMIT $chunk_size OFFSET $offset;"
  if ! run_csv_query "$query" "$chunk_file" "$chunk_err"; then
    code="$(classify_pg_error "$chunk_err")"
    echo "PG_CHUNKED_EXPORT=FAIL offset=$offset code=$code" | tee -a "$AUDIT"
    rm -f "$EXPORT_OUT"
    exit 1
  fi
  chunk_paths+=("$chunk_file")
  offset=$((offset + chunk_size))
  chunk_index=$((chunk_index + 1))
done

if python3 - "$EXPORT_OUT" "$expected_rows" "${chunk_paths[@]}" <<'PY'
import csv
import pathlib
import sys

output = pathlib.Path(sys.argv[1])
expected = int(sys.argv[2])
paths = [pathlib.Path(value) for value in sys.argv[3:]]
required = {"pattern_hash", "pattern", "count", "headings"}
fieldnames = None
rows = 0

try:
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = None
        for path in paths:
            with path.open("r", encoding="utf-8", newline="") as source:
                reader = csv.DictReader(source)
                current_fields = reader.fieldnames or []
                if not required.issubset(set(current_fields)):
                    raise ValueError("schema")
                if fieldnames is None:
                    fieldnames = current_fields
                    writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
                    writer.writeheader()
                elif current_fields != fieldnames:
                    raise ValueError("schema")
                for row in reader:
                    writer.writerow(row)
                    rows += 1
except (OSError, UnicodeError, csv.Error, ValueError):
    raise SystemExit(1)

if rows != expected:
    raise SystemExit(1)
PY
then
  chmod 600 "$EXPORT_OUT"
  report_csv "PG_PATTERN_LIBRARY_EXPORT=PASS mode=chunked chunks=$chunk_index" "$EXPORT_OUT"
  exit 0
else
  echo "PG_CHUNKED_EXPORT=FAIL code=PG_EXPORT_MERGE_OR_ROW_MISMATCH" | tee -a "$AUDIT"
  rm -f "$EXPORT_OUT"
  exit 1
fi
