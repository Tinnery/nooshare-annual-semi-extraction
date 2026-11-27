#!/usr/bin/env bash
# One-shot DEV market-data inventory. PostgreSQL transaction is explicitly READ ONLY.
# The resulting metadata-only archive is encrypted for this conversation and removed from the runner.
set -euo pipefail

WORK_DIR="${RUNNER_TEMP:-/tmp}"
OUT_DIR="$WORK_DIR/dev-market-data-inventory"
SQL_FILE="$WORK_DIR/dev-market-data-inventory.sql"
ZIP_OUT="$WORK_DIR/dev-market-data-inventory.zip"
ENCRYPTED_OUT="$WORK_DIR/dev-market-data-inventory.encrypted.json"
PG_PORT="${PG_LOCAL_PORT:-15432}"
PG_HOST="127.0.0.1"
PG_DB="nooshare_dev"
PG_USER="ci"

cleanup() {
  rm -rf "$OUT_DIR"
  rm -f "$SQL_FILE" "$ZIP_OUT"
  bash scripts/ci/teardown.sh >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "$PG_DB" != "nooshare_dev" ]]; then
  echo "DEV_MARKET_INVENTORY=FAIL code=DATABASE_TARGET_MISMATCH"
  exit 1
fi
if [[ -z "${PG_PASSWORD:-}" || -z "${STUNNEL_HOST:-}" || -z "${STUNNEL_PSK:-}" ]]; then
  echo "DEV_MARKET_INVENTORY=FAIL code=REQUIRED_SECRET_MISSING"
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -m 700 -p "$OUT_DIR"
rm -f "$ENCRYPTED_OUT"

# Keep tunnel startup, all SQL reads, and teardown inside this one CI step.
bash scripts/ci/build_stunnel.sh

cat > "$SQL_FILE" <<SQL
\\set ON_ERROR_STOP on
\\pset pager off
SET statement_timeout = '240s';
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

\\o $OUT_DIR/server.csv
SELECT current_database() AS database_name,
       current_user AS connected_role,
       current_setting('server_version') AS server_version,
       transaction_timestamp() AS snapshot_at;
\\o

\\o $OUT_DIR/schemas.csv
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

\\o $OUT_DIR/relations.csv
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
       pg_relation_size(c.oid)::bigint AS main_fork_bytes,
       pg_total_relation_size(c.oid)::bigint AS total_bytes,
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

\\o $OUT_DIR/columns.csv
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

\\o $OUT_DIR/constraints.csv
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

\\o $OUT_DIR/indexes.csv
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

\\o $OUT_DIR/relation_access.csv
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

\\o $OUT_DIR/market_data_ranges.csv
SELECT format(
  'SELECT %L AS relation, count(*)::bigint AS row_count, ' ||
  'count(DISTINCT %I)::bigint AS distinct_instruments, ' ||
  'min(%I)::text AS min_date, max(%I)::text AS max_date, ' ||
  'pg_total_relation_size(%L::regclass)::bigint AS total_bytes ' ||
  'FROM %I.%I',
  schema_name || '.' || relation_name,
  identity_column,
  date_column,
  date_column,
  schema_name || '.' || relation_name,
  schema_name,
  relation_name
)
FROM (VALUES
  ('tong', 'stock_daily', 'symbol', 'date'),
  ('tong', 'index_daily', 'symbol', 'date'),
  ('tong', 'etf_daily', 'symbol', 'date'),
  ('tong', 'gbbq', 'symbol', 'date'),
  ('public', 'hfq_daily', 'symbol', 'date'),
  ('public', 'canonical_symbol', 'symbol', 'list_date'),
  ('public', 'trading_calendar', 'market', 'cal_date'),
  ('indicators', 'daily_base_aligned', 'code', 'date')
) AS targets(schema_name, relation_name, identity_column, date_column)
WHERE to_regclass(format('%I.%I', schema_name, relation_name)) IS NOT NULL
ORDER BY schema_name, relation_name;
\\gexec
\\o

\\o $OUT_DIR/hfq_daily_field_fill.csv
SELECT format(
  'SELECT count(*)::bigint AS total_rows%s FROM public.hfq_daily',
  COALESCE(
    string_agg(
      format(
        ', count(*) FILTER (WHERE %I IS NOT NULL)::bigint AS present_%I, ' ||
        'count(*) FILTER (WHERE %I IS NULL)::bigint AS null_%I',
        column_name, column_name, column_name, column_name
      ),
      ''
      ORDER BY ordinal_position
    ),
    ''
  )
)
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'hfq_daily'
  AND column_name = ANY (ARRAY[
    'open', 'high', 'low', 'close',
    'open_hfq', 'high_hfq', 'low_hfq', 'close_hfq',
    'volume', 'amount', 'factor_cum', 'hfq_return'
  ])
HAVING count(*) > 0;
\\gexec
\\o

\\o $OUT_DIR/hfq_raw_consistency.csv
SELECT format(
  'SELECT count(DISTINCT (h.symbol, h.date))::bigint AS hfq_keys, ' ||
  'count(DISTINCT (r.symbol, r.date)) FILTER (WHERE r.symbol IS NOT NULL)::bigint AS matched_raw_keys, ' ||
  'count(DISTINCT (h.symbol, h.date)) FILTER (WHERE r.symbol IS NULL)::bigint AS missing_raw_keys%s ' ||
  'FROM public.hfq_daily h LEFT JOIN tong.stock_daily r ' ||
  'ON r.symbol = h.symbol AND r.date = h.date',
  COALESCE(
    string_agg(
      format(
        ', count(DISTINCT (h.symbol, h.date)) FILTER (WHERE h.%I IS DISTINCT FROM r.%I)::bigint AS mismatch_%I',
        c.column_name, c.column_name, c.column_name
      ),
      ''
      ORDER BY c.ordinal_position
    ),
    ''
  )
)
FROM information_schema.columns c
JOIN information_schema.columns r
  ON r.table_schema = 'tong'
 AND r.table_name = 'stock_daily'
 AND r.column_name = c.column_name
WHERE c.table_schema = 'public'
  AND c.table_name = 'hfq_daily'
  AND c.column_name = ANY (ARRAY['open', 'high', 'low', 'close', 'volume', 'amount'])
  AND to_regclass('tong.stock_daily') IS NOT NULL
HAVING count(*) > 0;
\\gexec
\\o

\\o $OUT_DIR/canonical_symbol_by_asset.csv
SELECT COALESCE(asset_class, '<NULL>') AS asset_class,
       COALESCE(exchange, '<NULL>') AS exchange,
       count(*)::bigint AS rows,
       count(DISTINCT canonical_id)::bigint AS distinct_canonical_ids,
       count(*) FILTER (WHERE list_date IS NULL)::bigint AS missing_list_date,
       count(*) FILTER (WHERE delist_date IS NOT NULL)::bigint AS delisted
FROM public.canonical_symbol
GROUP BY asset_class, exchange
ORDER BY asset_class, exchange;
\\o

\\o $OUT_DIR/canonical_symbol_mapping_coverage.csv
SELECT format(
  'SELECT %L AS relation, count(*)::bigint AS distinct_symbols, ' ||
  'count(*) FILTER (WHERE c.canonical_id IS NOT NULL)::bigint AS mapped_symbols, ' ||
  'count(*) FILTER (WHERE c.canonical_id IS NULL)::bigint AS unmapped_symbols ' ||
  'FROM (SELECT DISTINCT symbol FROM %I.%I) s ' ||
  'LEFT JOIN public.canonical_symbol c ON c.symbol = s.symbol',
  schema_name || '.' || relation_name,
  schema_name,
  relation_name
)
FROM (VALUES
  ('tong', 'stock_daily'),
  ('tong', 'index_daily'),
  ('tong', 'etf_daily'),
  ('public', 'hfq_daily')
) AS targets(schema_name, relation_name)
WHERE to_regclass(format('%I.%I', schema_name, relation_name)) IS NOT NULL
  AND to_regclass('public.canonical_symbol') IS NOT NULL
ORDER BY schema_name, relation_name;
\\gexec
\\o

\\o $OUT_DIR/tong_symbol_meta_by_class.csv
SELECT class,
       count(*)::bigint AS rows,
       count(DISTINCT symbol)::bigint AS distinct_symbols
FROM tong.symbol_meta
GROUP BY class
ORDER BY class;
\\o

\\o $OUT_DIR/tong_gbbq_by_category.csv
SELECT category,
       count(*)::bigint AS rows,
       count(DISTINCT symbol)::bigint AS distinct_symbols,
       min(date)::text AS min_date,
       max(date)::text AS max_date
FROM tong.gbbq
GROUP BY category
ORDER BY category;
\\o

\\o $OUT_DIR/data_freshness.csv
SELECT namespace, table_name, max_date, row_count, refreshed_at, status
FROM public.data_freshness
WHERE namespace = ANY (ARRAY['tong', 'public', 'indicators', 'ju', 'finance'])
ORDER BY namespace, table_name;
\\o

\\o $OUT_DIR/recent_pipeline_runs.csv
SELECT run_id, status, started_at, completed_at, code_commit, input_hash, output_hash
FROM public.pipeline_run
ORDER BY started_at DESC
LIMIT 20;
\\o

COMMIT;
SQL
chmod 600 "$SQL_FILE"

PGPASSWORD="$PG_PASSWORD" psql \
  -X --csv -v ON_ERROR_STOP=1 -P pager=off \
  -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  -f "$SQL_FILE" >/dev/null

python3 - "$OUT_DIR" "$ZIP_OUT" "$ENCRYPTED_OUT" <<'PY'
import base64
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

files = sorted(p for p in out_dir.glob("*.csv") if p.is_file())
if not files:
    raise SystemExit("DEV_MARKET_INVENTORY=FAIL code=EMPTY_SNAPSHOT")

manifest = {
    "format": "nooshare-dev-market-data-inventory-v1",
    "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
    "files": [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ],
}
(out_dir / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(out_dir.iterdir()):
        if path.is_file():
            archive.write(path, arcname=path.name)

archive_bytes = zip_path.read_bytes()
archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()

public_key_pem = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAzJNiTcbQhHU8PA3EuzUz
T+cIhG8TbzZG5Qo9AH4gSy+6zrxN5SCTTnG8fGCPgUPvVaYcTSEK0ygEDPddhVsp
+WMCERZ6w0YQWHmIWiqQR+GUqQ8zx0JcNtwLIu0JFNZts3C3uB2tha/CGjVe+0ni
5I/8AxV9xlptb4Mc+djDRB+ggaIWEldKXBFIoXIiXFSDZnpS4iqzfMCq2zFlnw8d
3rDgyijkTiLwJ0PoBBMsxelCwoVVKvpJ5xRFIyAZRbv8rtxiaXghpo36RdynkdJx
2nXVb/7JTA85AGq5o1bzpWCyYZ8uUi2uVl8XACVpebnXobwAIGYXypcJSREP9aQY
vKuTHNOnXv3mm2wp6SjsywD0f7b8f8fT+eGwaI5MUR9t7f4rYazuLlQKUgOA83dV
nai4inLrZDMrjTBgBSnI21S3gXV5Rzyl6NFFmg5OhTDc1DJSz1D1MZ1XjCg5zTKS
Lqu+O5vp8WwbabBBz8miFR1svW4euG4mAIup8mh3A26HAgMBAAE=
-----END PUBLIC KEY-----"""
public_key = serialization.load_pem_public_key(public_key_pem)

data_key = os.urandom(32)
nonce = os.urandom(12)
aad = b"nooshare:dev-market-data-inventory:v1"
ciphertext = AESGCM(data_key).encrypt(nonce, archive_bytes, aad)
wrapped_key = public_key.encrypt(
    data_key,
    padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None,
    ),
)

envelope = {
    "format": "nooshare-encrypted-inventory-v1",
    "key_wrap": "RSA-OAEP-SHA256",
    "content_encryption": "AES-256-GCM",
    "aad": base64.b64encode(aad).decode("ascii"),
    "nonce": base64.b64encode(nonce).decode("ascii"),
    "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
    "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    "archive_sha256": archive_sha256,
    "archive_bytes": len(archive_bytes),
    "file_count": len(files) + 1,
}
encrypted_path.write_text(
    json.dumps(envelope, separators=(",", ":")),
    encoding="utf-8",
)
os.chmod(encrypted_path, 0o600)
print(
    "DEV_MARKET_INVENTORY=PASS "
    f"files={len(files) + 1} "
    f"archive_bytes={len(archive_bytes)} "
    f"encrypted_bytes={encrypted_path.stat().st_size} "
    f"archive_sha256={archive_sha256}"
)
PY

test -s "$ENCRYPTED_OUT"
echo "DEV_MARKET_INVENTORY_TARGET=nooshare_dev"
