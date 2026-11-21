#!/usr/bin/env bash
# Bounded Pro read-only audit for Research. PG: one REPEATABLE READ READ ONLY
# session. RustFS: ListObjectsV2 + GetObject only; no PUT/DELETE or corpus dump.
set -euo pipefail

WORK_DIR="$RUNNER_TEMP"
test -n "$WORK_DIR" || WORK_DIR=/tmp
OUT_DIR="$WORK_DIR/research-pro-readonly-audit"
SQL_FILE="$WORK_DIR/research-pro-readonly-audit.sql"
PG_OUT="$WORK_DIR/research-pro-readonly-audit-psql.log"
PG_ERR="$WORK_DIR/research-pro-readonly-audit-error.log"
ZIP_OUT="$WORK_DIR/research-pro-readonly-audit.zip"
ENCRYPTED_OUT="$WORK_DIR/research-pro-readonly-audit.encrypted.json"
PG_PORT=15432

cleanup() {
  bash scripts/ci/teardown.sh >/dev/null 2>&1 || true
  rm -rf "$OUT_DIR"
  rm -f "$SQL_FILE" "$PG_OUT" "$PG_ERR" "$ZIP_OUT"
}
trap cleanup EXIT

: "$PG_PASSWORD"
: "$RUSTFS_ACCESS_KEY"
: "$RUSTFS_SECRET_KEY"
umask 077
rm -rf "$OUT_DIR"
mkdir -m 700 -p "$OUT_DIR"

# Reuse the repository's documented stunnel/SNI route, but do not call
# the existing run_probes.sh: that script writes and deletes a RustFS canary.
bash scripts/ci/build_stunnel.sh

cat > "$SQL_FILE" <<SQL
\set ON_ERROR_STOP on
SET statement_timeout = '180s';
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

\o $OUT_DIR/session.csv
SELECT current_database() AS database_name,
       current_user AS role_name,
       current_setting('server_version') AS server_version,
       current_setting('transaction_read_only') AS transaction_read_only,
       current_timestamp AS snapshot_time;
\o

\o $OUT_DIR/schema_relations.csv
SELECT n.nspname AS schema_name,
       c.relname AS relation_name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned_table'
         WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized_view'
         WHEN 'f' THEN 'foreign_table' ELSE c.relkind::text END AS relation_kind,
       c.reltuples::bigint AS estimated_rows,
       pg_total_relation_size(c.oid) AS total_bytes,
       has_table_privilege(current_user, c.oid, 'SELECT') AS can_select,
       has_table_privilege(current_user, c.oid, 'INSERT') AS can_insert,
       has_table_privilege(current_user, c.oid, 'UPDATE') AS can_update,
       has_table_privilege(current_user, c.oid, 'DELETE') AS can_delete
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('annual_semi','iwen','research','public')
  AND c.relkind IN ('r','p','v','m','f')
ORDER BY n.nspname, c.relname;
\o

\o $OUT_DIR/schema_privileges.csv
SELECT n.nspname AS schema_name,
       has_schema_privilege(current_user, n.oid, 'USAGE') AS can_usage,
       has_schema_privilege(current_user, n.oid, 'CREATE') AS can_create
FROM pg_catalog.pg_namespace n
WHERE n.nspname IN ('annual_semi','iwen','research','public')
ORDER BY n.nspname;
\o

\o $OUT_DIR/research_columns.csv
SELECT n.nspname AS schema_name, c.relname AS relation_name,
       a.attnum AS ordinal_position, a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS is_nullable,
       pg_get_expr(ad.adbin, ad.adrelid) AS default_expression
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = c.oid AND ad.adnum = a.attnum
WHERE n.nspname = 'research' AND c.relkind IN ('r','p','v','m')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum;
\o

\o $OUT_DIR/alembic_version.csv
SELECT 'public.alembic_version' AS location, version_num
FROM public.alembic_version;
\o

\o $OUT_DIR/research_table_catalog.csv
SELECT c.relname AS relation_name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'partitioned_table'
         WHEN 'v' THEN 'view' WHEN 'm' THEN 'materialized_view' ELSE c.relkind::text END AS relation_kind,
       c.reltuples::bigint AS estimated_rows,
       pg_total_relation_size(c.oid) AS total_bytes,
       has_table_privilege(current_user, c.oid, 'SELECT') AS can_select,
       has_table_privilege(current_user, c.oid, 'INSERT') AS can_insert,
       has_table_privilege(current_user, c.oid, 'UPDATE') AS can_update,
       has_table_privilege(current_user, c.oid, 'DELETE') AS can_delete
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'research' AND c.relkind IN ('r','p','v','m')
ORDER BY c.relname;
\o

\o $OUT_DIR/annual_semi_output_counts.csv
SELECT 'reconciled_report' AS relation, count(*) AS rows,
       count(DISTINCT stock_code || '_' || report_year::text || '_' || period::text) AS slots
FROM annual_semi.reconciled_report
UNION ALL SELECT 'h1_corpus_results', count(*), count(DISTINCT slot_key)
FROM annual_semi.h1_corpus_results
UNION ALL SELECT 'h1_fused_result', count(*), count(DISTINCT slot_key)
FROM annual_semi.h1_fused_result
UNION ALL SELECT 'h1_report_summary', count(*), count(DISTINCT slot_key)
FROM annual_semi.h1_report_summary
UNION ALL SELECT 'h1_pdf_result', count(*), count(DISTINCT slot_key)
FROM annual_semi.h1_pdf_result
UNION ALL SELECT 'h1_heading_detail', count(*), count(DISTINCT slot_key)
FROM annual_semi.h1_heading_detail
UNION ALL SELECT 'h1_pattern_library', count(*), count(*)
FROM annual_semi.h1_pattern_library
UNION ALL SELECT 'h2_pattern_library', count(*), count(*)
FROM annual_semi.h2_pattern_library
ORDER BY relation;
\o

\o $OUT_DIR/annual_semi_output_coverage.csv
WITH report_slots AS (
  SELECT stock_code || '_' || report_year::text || '_' || period::text AS slot_key
  FROM annual_semi.reconciled_report
),
h1_slots AS (SELECT DISTINCT slot_key FROM annual_semi.h1_corpus_results),
fused_slots AS (SELECT DISTINCT slot_key FROM annual_semi.h1_fused_result),
pdf_slots AS (SELECT DISTINCT slot_key FROM annual_semi.h1_pdf_result),
summary_slots AS (SELECT DISTINCT slot_key FROM annual_semi.h1_report_summary),
detail_slots AS (SELECT DISTINCT slot_key FROM annual_semi.h1_heading_detail)
SELECT
  (SELECT count(*) FROM report_slots) AS reconciled_slots,
  (SELECT count(*) FROM h1_slots) AS h1_slots,
  (SELECT count(*) FROM fused_slots) AS fused_slots,
  (SELECT count(*) FROM pdf_slots) AS pdf_slots,
  (SELECT count(*) FROM summary_slots) AS summary_slots,
  (SELECT count(*) FROM detail_slots) AS heading_detail_slots,
  (SELECT count(*) FROM report_slots r JOIN h1_slots x USING(slot_key)) AS reconciled_with_h1,
  (SELECT count(*) FROM report_slots r JOIN fused_slots x USING(slot_key)) AS reconciled_with_fused,
  (SELECT count(*) FROM report_slots r JOIN pdf_slots x USING(slot_key)) AS reconciled_with_pdf,
  (SELECT count(*) FROM report_slots r JOIN summary_slots x USING(slot_key)) AS reconciled_with_summary,
  (SELECT count(*) FROM report_slots r JOIN detail_slots x USING(slot_key)) AS reconciled_with_heading_details;
\o

\o $OUT_DIR/annual_semi_report_examples.csv
SELECT rr.stock_code,
       rr.report_year,
       rr.period,
       rr.stock_code || '_' || rr.report_year::text || '_' || rr.period::text AS slot_key,
       rr.winner_source,
       rr.winner_md_path,
       rr.content_sha256 AS reconciled_content_sha256,
       h.source_sha256 AS h1_source_sha256,
       h.n_bytes AS h1_n_bytes,
       h.n_headings,
       h.ordinal_valid,
       h.loaded_at
FROM annual_semi.reconciled_report rr
LEFT JOIN annual_semi.h1_corpus_results h
  ON h.slot_key = rr.stock_code || '_' || rr.report_year::text || '_' || rr.period::text
WHERE rr.winner_md_path IS NOT NULL
ORDER BY rr.report_year DESC, rr.stock_code
LIMIT 30;
\o

\o $OUT_DIR/annual_semi_h1_heading_examples.csv
SELECT slot_key, stock_code, report_year, period, source_sha256, n_bytes,
       n_headings, ordinal_valid, headings_json::text AS headings_json
FROM annual_semi.h1_corpus_results
WHERE headings_json IS NOT NULL
ORDER BY report_year DESC, slot_key
LIMIT 5;
\o

\o $OUT_DIR/annual_semi_heading_detail_examples.csv
SELECT slot_key, ordinal, marker, raw_name, canonical_name, canonical_cat,
       line_no, byte_start, byte_end, md_level, numbering_system,
       verbatim_line, extractor_version
FROM annual_semi.h1_heading_detail
WHERE slot_key = (
  SELECT slot_key FROM annual_semi.h1_corpus_results
  WHERE headings_json IS NOT NULL
  ORDER BY report_year DESC, slot_key LIMIT 1
)
ORDER BY ordinal
LIMIT 30;
\o

\o $OUT_DIR/annual_semi_file_current_state_examples.csv
SELECT to_jsonb(s)::text AS row_json
FROM annual_semi.file_current_state AS s
LIMIT 10;
\o

\o $OUT_DIR/iwen_limit_up_quality.csv
SELECT count(*) AS rows,
       count(DISTINCT stock_code) AS distinct_stocks,
       count(DISTINCT trade_date) AS distinct_trade_dates,
       min(trade_date) AS min_trade_date,
       max(trade_date) AS max_trade_date,
       min(refreshed_at) AS min_refreshed_at,
       max(refreshed_at) AS max_refreshed_at,
       count(*) FILTER (WHERE change_pct < 0) AS negative_change_pct,
       count(*) FILTER (WHERE change_pct IS NULL) AS null_change_pct,
       count(*) FILTER (WHERE limit_up_status IS DISTINCT FROM '涨停') AS status_not_limit_up,
       (SELECT count(*) FROM (
          SELECT trade_date FROM iwen.limit_up
          GROUP BY trade_date HAVING count(*) = 100
        ) capped_days) AS days_with_exactly_100_rows
FROM iwen.limit_up;
\o

COMMIT;
SQL
chmod 600 "$SQL_FILE"

PG_STATUS="PASS"
PG_ERROR_CODE="NONE"
if ! PGPASSWORD="$PG_PASSWORD" psql -X --csv -v ON_ERROR_STOP=1 \
    -h 127.0.0.1 -p "$PG_PORT" -U ci_probe -d nooshare_dev \
    -f "$SQL_FILE" > "$PG_OUT" 2> "$PG_ERR"; then
  PG_STATUS="FAIL"
  PG_ERROR_CODE="PG_READONLY_QUERY_FAILED"
  if grep -qi "permission denied" "$PG_ERR"; then PG_ERROR_CODE="PG_PERMISSION_DENIED"; fi
  if grep -qi "does not exist" "$PG_ERR"; then PG_ERROR_CODE="PG_OBJECT_OR_COLUMN_MISSING"; fi
  if grep -qiE "statement timeout|canceling statement" "$PG_ERR"; then PG_ERROR_CODE="PG_STATEMENT_TIMEOUT"; fi
  if grep -qiE "server closed the connection|unexpected eof|connection reset by peer|connection terminated unexpectedly" "$PG_ERR"; then PG_ERROR_CODE="PG_TUNNEL_DROPPED"; fi
fi

python3 - "$OUT_DIR" "$ZIP_OUT" "$ENCRYPTED_OUT" "$PG_STATUS" "$PG_ERROR_CODE" <<'PY'
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
pg_status, pg_error = sys.argv[4], sys.argv[5]

def rows_csv(name):
    path = out_dir / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))

# The only RustFS API operations here are LIST under annual-semi/published/
# and GET for paths independently obtained from annual_semi.reconciled_report.
rustfs = {
    "bucket": "annual-semi",
    "prefix": "published/",
    "operations": ["ListObjectsV2", "GetObject"],
    "objects_listed": [],
    "object_checks": [],
}
try:
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_LOCAL_ENDPOINT", "http://127.0.0.1:15500"),
        aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"],
        aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )
    listing = s3.list_objects_v2(Bucket="annual-semi", Prefix="published/", MaxKeys=25)
    for item in listing.get("Contents", []):
        rustfs["objects_listed"].append({
            "key": item.get("Key"),
            "size": int(item.get("Size", 0)),
            "etag": str(item.get("ETag", "")).strip('"'),
            "last_modified": item.get("LastModified").isoformat() if item.get("LastModified") else None,
        })

    seen = set()
    for row in rows_csv("annual_semi_report_examples.csv"):
        raw_path = (row.get("winner_md_path") or "").strip()
        expected = (row.get("reconciled_content_sha256") or "").strip().lower()
        key = raw_path
        if key.startswith("s3://annual-semi/"):
            key = key[len("s3://annual-semi/"):]
        elif key.startswith("annual-semi/"):
            key = key[len("annual-semi/"):]
        key = key.lstrip("/")
        if not key.startswith("published/") or key in seen:
            continue
        seen.add(key)
        result = {"key": key, "expected_sha256": expected or None}
        try:
            response = s3.get_object(Bucket="annual-semi", Key=key)
            digest = hashlib.sha256()
            size = 0
            body = response["Body"]
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
            body.close()
            actual = digest.hexdigest()
            result.update({
                "status": "GET_OK",
                "bytes": size,
                "actual_sha256": actual,
                "sha256_matches_reconciled": bool(expected and expected == actual),
                "etag": str(response.get("ETag", "")).strip('"'),
                "last_modified": response.get("LastModified").isoformat() if response.get("LastModified") else None,
            })
        except Exception as exc:
            result.update({"status": "GET_FAILED", "error_code": type(exc).__name__})
        rustfs["object_checks"].append(result)
        if len(rustfs["object_checks"]) >= 5:
            break
    rustfs["list_status"] = "OK"
except Exception as exc:
    rustfs["list_status"] = "FAILED"
    rustfs["list_error_code"] = type(exc).__name__

(out_dir / "rustfs_readonly_inventory.json").write_text(
    json.dumps(rustfs, ensure_ascii=False, indent=2), encoding="utf-8"
)

files = []
for path in sorted(out_dir.iterdir()):
    if path.is_file():
        raw = path.read_bytes()
        files.append({
            "name": path.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": max(sum(1 for _ in csv.reader(path.open("r", encoding="utf-8", newline=""))) - 1, 0)
                    if path.suffix == ".csv" else None,
        })

manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "workflow_sha": os.environ.get("GITHUB_SHA"),
    "database": "nooshare_dev",
    "pg_role": "ci_probe",
    "pg_transaction": "REPEATABLE READ READ ONLY",
    "pg_status": pg_status,
    "pg_error_code": pg_error,
    "rustfs_bucket": "annual-semi",
    "rustfs_prefix": "published/",
    "rustfs_read_only": True,
    "files": files,
}
(out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            archive.write(path, arcname=path.name)
zip_bytes = zip_path.read_bytes()

public_key_pem = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtMSE3YICKUIAcB9lnXtw
BeMnDLQSx26gbFS0ANbhHsVIR4Iwcr9glLtQ5DIFiqTQ0ec7RgRjVcM3EHGVg2Ya
cf1u7/9Zf15daeTMbmSVN2RoZs53OSYSw1nBRP0NBZeCw79iYaaHPTgFr2lhWmqp
ljoBMnzD0b39Q74MDci5/aW5vd8QdzYoTCX2y1FYKGFUgCGhrXujououqdRxETtc
UdR0fyFG4GvjMQsOeUXk/g7CPaZif8pZiUqtbViCfz6PKIaO5GpSHBjckatEExRw
q7ikiv25vWu2RfpB7AnHdpld5jeWn0od1zPli9cFry49xN2V2FHcSRNVl4SyA5c3
MwIDAQAB
-----END PUBLIC KEY-----"""
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

public_key = serialization.load_pem_public_key(public_key_pem)
data_key = os.urandom(32)
nonce = os.urandom(12)
aad = b"nooshare:research:pro-readonly-audit:v1"
ciphertext = AESGCM(data_key).encrypt(nonce, zip_bytes, aad)
wrapped = public_key.encrypt(
    data_key,
    padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                 algorithm=hashes.SHA256(), label=None),
)
envelope = {
    "version": 1,
    "key_wrap": "RSA-OAEP-SHA256",
    "content_encryption": "AES-256-GCM",
    "aad": base64.b64encode(aad).decode("ascii"),
    "nonce": base64.b64encode(nonce).decode("ascii"),
    "wrapped_key": base64.b64encode(wrapped).decode("ascii"),
    "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
}
encrypted_path.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
os.chmod(encrypted_path, 0o600)

print(f"PG_AUDIT={pg_status} code={pg_error}")
print(f"RUSTFS_LIST={rustfs['list_status']} listed={len(rustfs['objects_listed'])} checked={len(rustfs['object_checks'])}")
print(f"AUDIT_ARTIFACT bytes={len(zip_bytes)} encrypted_bytes={encrypted_path.stat().st_size} objects_are_metadata_only=1")
PY

test -s "$ENCRYPTED_OUT"
if [ "$PG_STATUS" != "PASS" ]; then
  echo "PG_AUDIT=FAIL code=$PG_ERROR_CODE"
  exit 1
fi
echo "RESEARCH_PRO_READONLY_AUDIT=PASS"
