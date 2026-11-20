#!/usr/bin/env bash
# Read-only matrix catalog export through the existing stunnel + SNI route.
# PG data stays in one psql session because this route has a constrained PG slot.
set -uo pipefail

WORK_DIR="${RUNNER_TEMP:-/tmp}"
OUT_DIR="$WORK_DIR/matrix-data-catalog"
SQL_FILE="$WORK_DIR/matrix-data-catalog.sql"
CONTROL_LOG="$WORK_DIR/matrix-data-catalog-control.log"
ERROR_LOG="$WORK_DIR/matrix-data-catalog-error.log"
ZIP_OUT="$WORK_DIR/matrix-data-catalog.zip"
ENCRYPTED_OUT="$WORK_DIR/iwen_limit_up.encrypted.json"
PG_PORT="${PG_LOCAL_PORT:-15432}"

cleanup() {
  rm -rf "$OUT_DIR"
  rm -f "$SQL_FILE" "$CONTROL_LOG" "$ERROR_LOG" "$ZIP_OUT"
}
trap cleanup EXIT

if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_MATRIX_CATALOG=FAIL code=PG_SECRET_MISSING"
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -m 700 -p "$OUT_DIR"
rm -f "$ENCRYPTED_OUT"

cat > "$SQL_FILE" <<SQL
\\set ON_ERROR_STOP on
SET statement_timeout = '180s';
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

\\o $OUT_DIR/matrix_schemas.csv
SELECT n.nspname AS schema_name,
       pg_get_userbyid(n.nspowner) AS owner_name,
       has_schema_privilege(current_user, n.oid, 'USAGE') AS can_usage,
       has_schema_privilege(current_user, n.oid, 'CREATE') AS can_create
FROM pg_catalog.pg_namespace n
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
ORDER BY n.nspname;
\\o

\\o $OUT_DIR/matrix_relations.csv
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       CASE c.relkind
         WHEN 'r' THEN 'table'
         WHEN 'p' THEN 'partitioned_table'
         WHEN 'v' THEN 'view'
         WHEN 'm' THEN 'materialized_view'
         WHEN 'f' THEN 'foreign_table'
         ELSE c.relkind::text
       END AS relation_kind,
       pg_get_userbyid(c.relowner) AS owner_name,
       c.reltuples::bigint AS estimated_rows,
       pg_relation_size(c.oid) AS main_fork_bytes,
       pg_total_relation_size(c.oid) AS total_bytes,
       c.relpersistence AS persistence
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
ORDER BY n.nspname, c.relname;
\\o

\\o $OUT_DIR/matrix_columns.csv
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       a.attnum AS ordinal_position,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS is_nullable,
       pg_get_expr(ad.adbin, ad.adrelid) AS default_expression
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
LEFT JOIN pg_catalog.pg_attrdef ad
       ON ad.adrelid = c.oid AND ad.adnum = a.attnum
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum;
\\o

\\o $OUT_DIR/matrix_constraints.csv
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       con.conname AS constraint_name,
       con.contype AS constraint_type,
       pg_get_constraintdef(con.oid, true) AS definition
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
ORDER BY n.nspname, c.relname, con.conname;
\\o

\\o $OUT_DIR/matrix_indexes.csv
SELECT n.nspname AS schema_name,
       t.relname AS relation_name,
       i.relname AS index_name,
       ix.indisprimary AS is_primary,
       ix.indisunique AS is_unique,
       pg_get_indexdef(i.oid) AS definition
FROM pg_catalog.pg_index ix
JOIN pg_catalog.pg_class t ON t.oid = ix.indrelid
JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
ORDER BY n.nspname, t.relname, i.relname;
\\o

\\o $OUT_DIR/matrix_access.csv
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       has_table_privilege(current_user, c.oid, 'SELECT') AS can_select,
       has_table_privilege(current_user, c.oid, 'INSERT') AS can_insert,
       has_table_privilege(current_user, c.oid, 'UPDATE') AS can_update,
       has_table_privilege(current_user, c.oid, 'DELETE') AS can_delete,
       has_table_privilege(current_user, c.oid, 'TRUNCATE') AS can_truncate
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY (ARRAY[
  'iwen', 'ju', 'tong', 'finance', 'capital', 'raw', 'meta',
  'annual_semi', 'public', 'indicators', 'strategy', 'research'
])
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
ORDER BY n.nspname, c.relname;
\\o

\\o $OUT_DIR/annual_semi_reconciled_report_by_period.csv
SELECT report_year,
       period,
       count(*) AS rows,
       count(DISTINCT stock_code) AS distinct_stocks,
       min(stock_code) AS first_stock_code,
       max(stock_code) AS last_stock_code
FROM annual_semi.reconciled_report
GROUP BY report_year, period
ORDER BY report_year, period;
\\o

\\o $OUT_DIR/annual_semi_h1_corpus_summary.csv
SELECT report_year,
       period,
       count(*) AS rows,
       count(*) FILTER (WHERE headings_json IS NOT NULL) AS headings_present,
       count(*) FILTER (WHERE headings_json IS NULL) AS headings_null,
       count(*) FILTER (WHERE ordinal_valid IS TRUE) AS ordinal_valid,
       count(*) FILTER (WHERE ordinal_valid IS FALSE) AS ordinal_invalid
FROM annual_semi.h1_corpus_results
GROUP BY report_year, period
ORDER BY report_year, period;
\\o

\\o $OUT_DIR/annual_semi_pattern_library_summary.csv
SELECT 'h1_pattern_library' AS library,
       count(*) AS rows,
       min(count) AS min_frequency,
       max(count) AS max_frequency
FROM annual_semi.h1_pattern_library
UNION ALL
SELECT 'h2_pattern_library',
       count(*),
       min(count),
       max(count)
FROM annual_semi.h2_pattern_library
ORDER BY library;
\\o

\\o $OUT_DIR/iwen_limit_up_summary.csv
SELECT count(*) AS rows,
       count(DISTINCT stock_code) AS distinct_stocks,
       count(DISTINCT trade_date) AS distinct_trade_dates,
       min(trade_date) AS min_trade_date,
       max(trade_date) AS max_trade_date,
       min(refreshed_at) AS min_refreshed_at,
       max(refreshed_at) AS max_refreshed_at
FROM iwen.limit_up;
\\o


\o $OUT_DIR/annual_semi_output_coverage.csv
WITH report_slots AS (
  SELECT stock_code || '_' || report_year::text || '_' || period::text AS slot_key
  FROM annual_semi.reconciled_report
),
h1_slots AS (
  SELECT DISTINCT slot_key FROM annual_semi.h1_corpus_results
),
fused_slots AS (
  SELECT DISTINCT slot_key FROM annual_semi.h1_fused_result
),
pdf_slots AS (
  SELECT DISTINCT slot_key FROM annual_semi.h1_pdf_result
),
summary_slots AS (
  SELECT DISTINCT slot_key FROM annual_semi.h1_report_summary
),
detail_slots AS (
  SELECT slot_key, count(*) AS detail_rows
  FROM annual_semi.h1_heading_detail
  GROUP BY slot_key
)
SELECT
  (SELECT count(*) FROM report_slots) AS reconciled_report_slots,
  (SELECT count(*) FROM h1_slots) AS h1_corpus_slots,
  (SELECT count(*) FROM fused_slots) AS h1_fused_slots,
  (SELECT count(*) FROM pdf_slots) AS h1_pdf_slots,
  (SELECT count(*) FROM summary_slots) AS h1_summary_slots,
  (SELECT count(*) FROM detail_slots) AS h1_heading_detail_slots,
  (SELECT coalesce(sum(detail_rows), 0) FROM detail_slots) AS h1_heading_detail_rows,
  (SELECT count(*) FROM report_slots r JOIN h1_slots x USING (slot_key)) AS reconciled_with_h1,
  (SELECT count(*) FROM report_slots r JOIN fused_slots x USING (slot_key)) AS reconciled_with_fused,
  (SELECT count(*) FROM report_slots r JOIN pdf_slots x USING (slot_key)) AS reconciled_with_pdf,
  (SELECT count(*) FROM report_slots r JOIN summary_slots x USING (slot_key)) AS reconciled_with_summary,
  (SELECT count(*) FROM report_slots r JOIN detail_slots x USING (slot_key)) AS reconciled_with_heading_details;
\o

\o $OUT_DIR/annual_semi_output_table_counts.csv
SELECT 'reconciled_report' AS relation, count(*) AS rows, count(*) AS distinct_slots FROM annual_semi.reconciled_report
UNION ALL
SELECT 'h1_corpus_results', count(*), count(DISTINCT slot_key) FROM annual_semi.h1_corpus_results
UNION ALL
SELECT 'h1_fused_result', count(*), count(DISTINCT slot_key) FROM annual_semi.h1_fused_result
UNION ALL
SELECT 'h1_report_summary', count(*), count(DISTINCT slot_key) FROM annual_semi.h1_report_summary
UNION ALL
SELECT 'h1_pdf_result', count(*), count(DISTINCT slot_key) FROM annual_semi.h1_pdf_result
UNION ALL
SELECT 'h1_heading_detail', count(*), count(DISTINCT slot_key) FROM annual_semi.h1_heading_detail
UNION ALL
SELECT 'h1_pattern_library', count(*), count(*) FROM annual_semi.h1_pattern_library
UNION ALL
SELECT 'h2_pattern_library', count(*), count(*) FROM annual_semi.h2_pattern_library
ORDER BY relation;
\o

\o $OUT_DIR/matrix_market_data_ranges.csv
SELECT 'tong.stock_daily' AS relation,
       count(*) AS rows,
       count(DISTINCT symbol) AS securities,
       min(date)::text AS min_date,
       max(date)::text AS max_date
FROM tong.stock_daily
UNION ALL
SELECT 'public.hfq_daily',
       count(*),
       count(DISTINCT symbol),
       min(date)::text,
       max(date)::text
FROM public.hfq_daily
UNION ALL
SELECT 'indicators.daily_base_aligned',
       count(*),
       count(DISTINCT code),
       min(date)::text,
       max(date)::text
FROM indicators.daily_base_aligned
UNION ALL
SELECT 'ju.trading_day',
       count(*),
       count(*) FILTER (WHERE is_trading_day IS TRUE),
       min(trade_date)::text,
       max(trade_date)::text
FROM ju.trading_day
UNION ALL
SELECT 'finance.income_statement',
       count(*),
       count(DISTINCT code),
       min(report_date)::text,
       max(report_date)::text
FROM finance.income_statement
ORDER BY relation;
\o

\o $OUT_DIR/public_pit_quality.csv
SELECT 'canonical_symbol' AS relation,
       count(*) AS rows,
       count(DISTINCT canonical_id) AS distinct_ids,
       count(*) FILTER (WHERE delist_date IS NOT NULL) AS delisted,
       NULL::bigint AS missing_publication_dates
FROM public.canonical_symbol
UNION ALL
SELECT 'corporate_action_event',
       count(*),
       count(DISTINCT event_id),
       count(*) FILTER (WHERE event_type IN ('st_mark', 'st_remove')),
       count(*) FILTER (WHERE pub_date IS NULL)
FROM public.corporate_action_event
UNION ALL
SELECT 'finance.income_statement',
       count(*),
       count(DISTINCT code || ':' || report_date::text),
       NULL::bigint,
       count(*) FILTER (WHERE pub_date IS NULL)
FROM finance.income_statement
ORDER BY relation;
\o

\o $OUT_DIR/iwen_limit_up_field_semantics.csv
SELECT count(*) AS rows,
       count(*) FILTER (WHERE latest_price IS NULL) AS latest_price_nulls,
       count(*) FILTER (WHERE latest_price = 0) AS latest_price_zeros,
       count(*) FILTER (WHERE change_pct IS NULL) AS change_pct_nulls,
       count(*) FILTER (WHERE change_pct < 0) AS change_pct_negative,
       count(*) FILTER (WHERE change_pct = 0) AS change_pct_zero,
       count(*) FILTER (WHERE change_pct > 0) AS change_pct_positive,
       count(*) FILTER (WHERE continuous_days IS NULL) AS continuous_days_nulls,
       count(*) FILTER (WHERE continuous_days = 0) AS continuous_days_zeros,
       count(*) FILTER (WHERE limit_up_open_count IS NULL) AS open_count_nulls,
       count(*) FILTER (WHERE limit_up_open_count = 0) AS open_count_zeros,
       count(*) FILTER (WHERE limit_up_reason IS NULL OR btrim(limit_up_reason) = '') AS reason_missing,
       count(*) FILTER (WHERE limit_up_status IS DISTINCT FROM '涨停') AS status_not_limit_up
FROM iwen.limit_up;
\o

\o $OUT_DIR/annual_semi_event_lifecycle_summary.csv
SELECT event_type, count(*) AS events,
       min(occurred_at) AS first_seen,
       max(occurred_at) AS last_seen
FROM annual_semi.file_lifecycle
GROUP BY event_type
ORDER BY event_type;
\o

COMMIT;
SQL
chmod 600 "$SQL_FILE"

query_status="PASS"
error_code="NONE"
if ! PGPASSWORD="$PG_PASSWORD" psql -X --csv -v ON_ERROR_STOP=1 \
    -h 127.0.0.1 -p "$PG_PORT" -U ci_probe -d nooshare_dev \
    -f "$SQL_FILE" > "$CONTROL_LOG" 2> "$ERROR_LOG"; then
  query_status="FAIL"
  error_code="PG_MATRIX_QUERY_FAILED"
  if grep -qi "permission denied" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_MATRIX_PERMISSION_DENIED"
  elif grep -qi "does not exist" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_MATRIX_OBJECT_MISSING"
  elif grep -qiE "statement timeout|canceling statement" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_MATRIX_STATEMENT_TIMEOUT"
  elif grep -qiE "server closed the connection|unexpected eof|connection reset by peer|SSL SYSCALL error.*EOF|connection terminated unexpectedly" "$ERROR_LOG" 2>/dev/null; then
    error_code="PG_MATRIX_TUNNEL_DROP"
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

rustfs_inventory = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "endpoint": "local-stunnel-s3",
    "buckets": [],
}
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_LOCAL_ENDPOINT", "http://127.0.0.1:15500"),
        aws_access_key_id=os.environ.get("RUSTFS_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("RUSTFS_SECRET_KEY", ""),
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )

    bucket_response = s3.list_buckets()
    bucket_names = sorted(b.get("Name", "") for b in bucket_response.get("Buckets", []) if b.get("Name"))
    rustfs_inventory["bucket_names"] = bucket_names
    for bucket in bucket_names:
        prefix = "published/" if bucket == "annual-semi" else ""
        entry = {"bucket": bucket, "prefix": prefix, "status": "unknown", "objects": []}
        try:
            response = s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=30,
            )
            entry["status"] = "available"
            entry["is_truncated"] = bool(response.get("IsTruncated", False))
            for obj in response.get("Contents", []):
                entry["objects"].append({
                    "key": obj.get("Key"),
                    "size": int(obj.get("Size", 0)),
                    "last_modified": obj.get("LastModified").isoformat()
                    if obj.get("LastModified") else None,
                    "etag": obj.get("ETag", "").strip('"'),
                })
        except ClientError as exc:
            entry["status"] = "unavailable"
            entry["error_code"] = exc.response.get("Error", {}).get("Code", "S3_CLIENT_ERROR")
        except Exception as exc:
            entry["status"] = "unavailable"
            entry["error_code"] = type(exc).__name__
        rustfs_inventory["buckets"].append(entry)
except Exception as exc:
    rustfs_inventory["status"] = "client_unavailable"
    rustfs_inventory["error_code"] = type(exc).__name__

(out_dir / "rustfs_object_inventory.json").write_text(
    json.dumps(rustfs_inventory, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

files = []
for path in sorted(out_dir.iterdir()):
    if path.is_file():
        raw = path.read_bytes()
        files.append({
            "name": path.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": row_count(path) if path.suffix == ".csv" else None,
        })

manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "database": "nooshare_dev",
    "schemas_requested": [
        "iwen", "ju", "tong", "finance", "capital", "raw", "meta",
        "annual_semi", "public", "indicators", "strategy", "research",
    ],
    "query_status": query_status,
    "error_code": error_code,
    "rustfs_inventory_status": rustfs_inventory.get("status", "partial"),
    "files": files,
}
(out_dir / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            archive.write(path, arcname=path.name)

zip_bytes = zip_path.read_bytes()
zip_hash = hashlib.sha256(zip_bytes).hexdigest()

public_key_pem = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAirFQHGOSzkPY0wrtJ/A+
Z7js7/9Jzr1YQUxV1e2P325zamACkn0v4ZSyC0PNsGCRZyNcr1QCl2w752aBwlEH
GgdRBkX38FmzN9jd6Z6E6wHChH2uqSmUHG2gE8Mc/v2nan0N7QL8Dm9oLUrk7fDy
L9eDjjDbbxJzUdu5tEt/m9NbKPKz9yPQm9HnBp0TylF34AIR//xLlpUl6TfKI8ZB
dlwt0IyJ3cFlXfYzVklhumJVU45ru6B5Ml0ZN2iCkOH8/O9dlJ4ZJYDMTHmbt7FB
2CyGC4RU9ZhBOJnrgTlQVH3Cu4NEesk7sbLdrm1xQTWsvsPoh6qZSgJxPq3ExZcS
k1vb6174xQXWLlnq+M6i7KV74VZK3q032NbE9VMAi4sIyfmcl/lip1nBv7xGbSIL
NzJ/Xi3v0vnKVqNLvku4gOd3MCkE6ek1yqo2ZYreUw378wdkLcpXzJjU9nNNgHPB
rbCQseXICgGCGWotnQiE5+N6AuRmRwz5Qxru+ICqV2vJAgMBAAE=
-----END PUBLIC KEY-----"""
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

public_key = serialization.load_pem_public_key(public_key_pem)
data_key = os.urandom(32)
nonce = os.urandom(12)
aad = b"nooshare:matrix:pg-rustfs-catalog:readonly:v1"
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

tables = next((x["rows"] for x in files if x["name"] == "matrix_relations.csv"), 0)
columns = next((x["rows"] for x in files if x["name"] == "matrix_columns.csv"), 0)
status = "PASS" if query_status == "PASS" else "PARTIAL"
print(
    f"PG_MATRIX_CATALOG={status} relations={tables} columns={columns} "
    f"zip_bytes={len(zip_bytes)} zip_sha256={zip_hash} "
    f"encrypted_bytes={encrypted_path.stat().st_size} error_code={error_code}"
)
PY

if [ "$query_status" = "FAIL" ]; then
  echo "PG_MATRIX_CATALOG=FAIL code=$error_code"
  exit 1
fi
exit 0
