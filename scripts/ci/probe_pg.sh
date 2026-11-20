#!/usr/bin/env bash
# PG 真连探针（经 stunnel 本地端口）。只读导出 H1 Pattern Library 并校验行数。
# 失败只输出固定错误码，绝不回显原始错误（可能含连接信息）。
set -uo pipefail

AUDIT="${RUNNER_TEMP:-/tmp}/ci_audit.log"
# 连接参数全部固定，使用专用只读角色。仅密码通过 secret 注入。
PG_HOST="127.0.0.1"
PG_PORT="${PG_LOCAL_PORT:-15432}"
PG_DB="nooshare_dev"
PG_USER="ci_probe"
EXPORT_OUT="${RUNNER_TEMP:-/tmp}/h1_pattern_library.csv"
EXPORT_ERR="${RUNNER_TEMP:-/tmp}/h1_pattern_library_export_err.txt"

if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_PROBE=FAIL code=PG_SECRET_MISSING" | tee -a "$AUDIT"
  exit 1
fi

rm -f "$EXPORT_OUT" "$EXPORT_ERR"

# Use one PostgreSQL session for the complete SELECT. The CI SNI router has a
# constrained connection slot per PSK identity, so avoid a count query followed
# by a second connection for the data export.
if PGPASSWORD="$PG_PASSWORD" psql \
    -X --csv -v ON_ERROR_STOP=1 \
    -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    -c "SELECT * FROM annual_semi.h1_pattern_library ORDER BY pattern_hash;" \
    > "$EXPORT_OUT" 2> "$EXPORT_ERR"; then
  chmod 600 "$EXPORT_OUT"
  if python3 - "$EXPORT_OUT" <<'PY'
import csv
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
with path.open("r", encoding="utf-8", newline="") as stream:
    reader = csv.DictReader(stream)
    fields = reader.fieldnames or []
    if not {"pattern_hash", "pattern", "count", "headings"}.issubset(fields):
        print("PG_PATTERN_LIBRARY_EXPORT=FAIL code=SCHEMA_MISMATCH")
        raise SystemExit(1)
    rows = sum(1 for _ in reader)

if rows <= 0:
    print("PG_PATTERN_LIBRARY_EXPORT=FAIL code=EMPTY_RESULT")
    raise SystemExit(1)

digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"PG_PROBE=PASS patterns={rows}")
print(f"PG_PATTERN_LIBRARY_EXPORT=PASS rows={rows} bytes={path.stat().st_size} sha256={digest}")
PY
  then
    result=0
  else
    rm -f "$EXPORT_OUT"
    result=1
  fi
else
  code="PG_EXPORT_QUERY_FAILED"
  if grep -qi "permission denied" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_PERMISSION_DENIED"
  elif grep -qi "server closed the connection\|unexpected eof" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_TUNNEL_DROP"
  elif grep -qi "connection refused" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_TCP_REFUSED"
  elif grep -qi "could not connect to server\|timeout\|timed out" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_TIMEOUT"
  elif grep -qi "no pg_hba.conf entry" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_HBA_DENY"
  elif grep -qi "does not exist" "$EXPORT_ERR" 2>/dev/null; then
    code="PG_EXPORT_OBJECT_MISSING"
  fi
  rm -f "$EXPORT_OUT"
  echo "PG_PROBE=FAIL code=$code" | tee -a "$AUDIT"
  result=1
fi

# Keep the CSV only for the subsequent one-day Actions artifact upload.
shred -u "$EXPORT_ERR" 2>/dev/null || rm -f "$EXPORT_ERR"

exit "$result"
