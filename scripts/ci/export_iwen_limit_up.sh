#!/usr/bin/env bash
# One-shot read-only iwen export. Plaintext remains under RUNNER_TEMP and is deleted.
set -uo pipefail
WORK_DIR="${RUNNER_TEMP:-/tmp}"
OUT_DIR="$WORK_DIR/iwen-limit-up-export"
SQL_FILE="$WORK_DIR/iwen-limit-up-export.sql"
CONTROL_LOG="$WORK_DIR/iwen-limit-up-control.log"
ERROR_LOG="$WORK_DIR/iwen-limit-up-error.log"
ZIP_OUT="$WORK_DIR/iwen-limit-up-export.zip"
ENCRYPTED_OUT="$WORK_DIR/iwen_limit_up.encrypted.json"
PG_PORT="${PG_LOCAL_PORT:-15432}"

cleanup() {
  rm -rf "$OUT_DIR"
  rm -f "$SQL_FILE" "$CONTROL_LOG" "$ERROR_LOG" "$ZIP_OUT"
}
trap cleanup EXIT

if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_IWEN_EXPORT=FAIL code=PG_SECRET_MISSING"
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -m 700 -p "$OUT_DIR"
rm -f "$ENCRYPTED_OUT"

cat > "$SQL_FILE" <<SQL
\set ON_ERROR_STOP on
SET statement_timeout = '180s';
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

\o $OUT_DIR/iwen_tables.csv
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       c.relkind AS relation_kind,
       pg_get_userbyid(c.relowner) AS owner_name,
       c.reltuples::bigint AS estimated_rows,
       pg_total_relation_size(c.oid) AS relation_bytes
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'iwen'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
ORDER BY c.relname;
\o

\o $OUT_DIR/iwen_columns.csv
SELECT c.relname AS table_name,
       a.attnum AS ordinal_position,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS is_nullable
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'iwen'
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;
\o

\o $OUT_DIR/iwen_limit_up_access.csv
SELECT current_user AS role_name,
       (to_regnamespace('iwen') IS NOT NULL) AS schema_exists,
       CASE WHEN to_regnamespace('iwen') IS NOT NULL
            THEN has_schema_privilege(current_user, to_regnamespace('iwen'), 'USAGE')
            ELSE FALSE END AS schema_usage,
       (to_regclass('iwen.limit_up') IS NOT NULL) AS relation_exists,
       CASE WHEN to_regclass('iwen.limit_up') IS NOT NULL
            THEN has_table_privilege(current_user, to_regclass('iwen.limit_up'), 'SELECT')
            ELSE FALSE END AS table_select,
       CASE WHEN to_regnamespace('iwen') IS NOT NULL
                  AND to_regclass('iwen.limit_up') IS NOT NULL
            THEN has_schema_privilege(current_user, to_regnamespace('iwen'), 'USAGE')
                 AND has_table_privilege(current_user, to_regclass('iwen.limit_up'), 'SELECT')
            ELSE FALSE END AS can_read;
\o

SELECT CASE
         WHEN to_regnamespace('iwen') IS NOT NULL
          AND to_regclass('iwen.limit_up') IS NOT NULL
          AND has_schema_privilege(current_user, to_regnamespace('iwen'), 'USAGE')
          AND has_table_privilege(current_user, to_regclass('iwen.limit_up'), 'SELECT')
         THEN 'true' ELSE 'false'
       END AS can_read
\gset

\if :can_read
\echo PG_IWEN_LIMIT_UP_ACCESS=GRANTED

\o $OUT_DIR/limit_up_all.csv
SELECT * FROM iwen.limit_up ORDER BY trade_date DESC, stock_code;
\o

\o $OUT_DIR/limit_up_2024.csv
SELECT * FROM iwen.limit_up
WHERE trade_date BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY trade_date DESC, stock_code;
\o

\o $OUT_DIR/limit_up_000001.csv
SELECT * FROM iwen.limit_up
WHERE stock_code = '000001'
ORDER BY trade_date DESC;
\o

\o $OUT_DIR/limit_up_continuous_ge3.csv
SELECT stock_code, trade_date, continuous_days, limit_up_reason, days_boards
FROM iwen.limit_up
WHERE continuous_days >= 3
ORDER BY continuous_days DESC, trade_date DESC;
\o

\o $OUT_DIR/limit_up_top20_seal_amount.csv
SELECT stock_code, trade_date, limit_up_seal_amount, change_pct, limit_up_reason
FROM iwen.limit_up
WHERE limit_up_seal_amount IS NOT NULL
ORDER BY limit_up_seal_amount DESC
LIMIT 20;
\o

\o $OUT_DIR/limit_up_reason_counts.csv
SELECT limit_up_reason, count(*) AS cnt
FROM iwen.limit_up
WHERE limit_up_reason IS NOT NULL
GROUP BY limit_up_reason
ORDER BY cnt DESC;
\o

\o $OUT_DIR/limit_up_early_morning.csv
SELECT stock_code, trade_date, first_limit_up_time, continuous_days
FROM iwen.limit_up
WHERE first_limit_up_time < '10:00'
ORDER BY trade_date DESC, first_limit_up_time;
\o
\else
\echo PG_IWEN_LIMIT_UP_ACCESS=DENIED
\endif
COMMIT;
SQL
chmod 600 "$SQL_FILE"

query_status="PASS"
error_code="NONE"
if ! PGPASSWORD="$PG_PASSWORD" psql -X --csv -v ON_ERROR_STOP=1 \
    -h 127.0.0.1 -p "$PG_PORT" -U ci_probe -d nooshare_dev \
    -f "$SQL_FILE" > "$CONTROL_LOG" 2> "$ERROR_LOG"; then
  query_status="FAIL"
  error_code="PG_IWEN_QUERY_FAILED"
  if grep -qi "permission denied" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_IWEN_PERMISSION_DENIED"
  elif grep -qi "does not exist" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_IWEN_OBJECT_MISSING"
  elif grep -qiE "statement timeout|canceling statement" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_IWEN_STATEMENT_TIMEOUT"
  elif grep -qiE "server closed the connection|unexpected eof|connection reset by peer|SSL SYSCALL error.*EOF|connection terminated unexpectedly" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_IWEN_TUNNEL_DROP"
  fi
fi

python3 - "$OUT_DIR" "$ZIP_OUT" "$ENCRYPTED_OUT" "$query_status" "$error_code" <<'PY'
import base64
import csv
import hashlib
import json
import os
import pathlib
import sys
import zipfile
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

out_dir = pathlib.Path(sys.argv[1])
zip_path = pathlib.Path(sys.argv[2])
encrypted_path = pathlib.Path(sys.argv[3])
query_status = sys.argv[4]
error_code = sys.argv[5]

def row_count(path):
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as stream:
        return max(sum(1 for _ in csv.reader(stream)) - 1, 0)

files = []
for path in sorted(out_dir.glob("*.csv")):
    raw = path.read_bytes()
    files.append({
        "name": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": row_count(path),
    })

access = {}
access_file = out_dir / "iwen_limit_up_access.csv"
if access_file.exists():
    with access_file.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if rows:
        access = rows[0]

can_read = str(access.get("can_read", "false")).lower() in {"true", "t", "1"}
manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "database": "nooshare_dev",
    "schema": "iwen",
    "table": "limit_up",
    "query_status": query_status,
    "error_code": error_code,
    "access": access,
    "files": files,
}
(out_dir / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            archive.write(path, arcname=path.name)

zip_bytes = zip_path.read_bytes()
zip_hash = hashlib.sha256(zip_bytes).hexdigest()
public_key_pem = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAqqwiycUjELf5Eeo/SzQB
9ED+xKtUi5RPwm/R62yhV3YBgY9WeQN/7fX8zoE0/WzdzdOhWG0iYY2+fHz7EtrI
IWYBtPIBuhtr8W0I3Hq0y1JR1Y5Hl8QONHaDzFbWWI4YGcmjlh9VVfFEQ2s6EWgJ
EZbt7hunYx/Io+kxgvLcM1G9pLbtAIxt7+A6mfvSzCU5PTLLpUNQQkbqJ1dABEJU
QAgxJZwVq+VkMYh94ghk4XG9eJkVD75qqaBwGNPgVkk30T2yvmhL5lGUoSx9IWOX
04mrmbc6/Fr6nx6wir8qOMwJ6S1cpzdQLoLdX03YmEQblKLgFGCfBEKxmYZxPst5
KSveLzQs3It0OoXfIaBv12gRuS3Y5UHb18r9PTlg5xzX9ggp4AhvEWh9sdT8db3/
irwMEQWDNc5KDMUT755yJkpJQAxH5X3s+EMhUi/qjPThvRGQfnSMyl9KLeDpoJsz
goQj/f3ZJgy/3oJdsFzvjYHzcPkNnlx7landr6fru/ktAgMBAAE=
-----END PUBLIC KEY-----
"""
public_key = serialization.load_pem_public_key(public_key_pem)
data_key = os.urandom(32)
nonce = os.urandom(12)
aad = b"nooshare:iwen:limit_up:readonly:v1"
ciphertext = AESGCM(data_key).encrypt(nonce, zip_bytes, aad)
wrapped_key = public_key.encrypt(
    data_key,
    padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ),
)
envelope = {
    "version": 1,
    "key_wrap": "RSA-OAEP-SHA256",
    "content_encryption": "AES-256-GCM",
    "aad": base64.b64encode(aad).decode("ascii"),
    "nonce": base64.b64encode(nonce).decode("ascii"),
    "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
    "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
}
encrypted_path.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
os.chmod(encrypted_path, 0o600)

table_count = row_count(out_dir / "iwen_tables.csv")
all_rows = next((x["rows"] for x in files if x["name"] == "limit_up_all.csv"), 0)
reason_groups = next((x["rows"] for x in files if x["name"] == "limit_up_reason_counts.csv"), 0)
status = "PASS" if query_status == "PASS" and can_read else "PARTIAL"
print(
    f"PG_IWEN_EXPORT={status} can_read={str(can_read).lower()} "
    f"iwen_relations={table_count} limit_up_rows={all_rows} "
    f"reason_groups={reason_groups} zip_bytes={len(zip_bytes)} "
    f"zip_sha256={zip_hash} encrypted_bytes={encrypted_path.stat().st_size} "
    f"error_code={error_code}"
)
PY

if [ "$query_status" = "FAIL" ]; then
  echo "PG_IWEN_EXPORT=FAIL code=$error_code"
  exit 1
fi
exit 0
