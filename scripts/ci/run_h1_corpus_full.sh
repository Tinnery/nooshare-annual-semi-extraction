#!/usr/bin/env bash
# Resumable, bounded-memory full H1 run. Each chunk is downloaded, extracted,
# upserted to PG, and then its raw MD files are deleted before the next chunk.
set -uo pipefail

WORK_DIR="${RUNNER_TEMP:-/tmp}"
AUDIT="$WORK_DIR/ci_audit.log"
rm -f "$AUDIT"

cleanup() {
  bash scripts/ci/teardown.sh
}
trap cleanup EXIT

BATCH_SIZE="${H1_CORPUS_BATCH_SIZE:-1000}"
EXPECTED_TOTAL="${H1_EXPECTED_CORPUS_COUNT:-0}"
PROCESSED_BEFORE="${H1_PROCESSED_BEFORE:-0}"
PROCESS_LIMIT="${H1_PROCESS_LIMIT:-0}"
CURSOR="${CORPUS_START_AFTER:-}"
PG_LOCAL="${PG_LOCAL_PORT:-15432}"
S3_LOCAL="${S3_LOCAL_PORT:-15500}"

if ! [[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  echo "ORCHESTRATOR=FAIL code=INVALID_BATCH_SIZE"
  exit 1
fi
if ! [[ "$EXPECTED_TOTAL" =~ ^[0-9]+$ ]] || ! [[ "$PROCESSED_BEFORE" =~ ^[0-9]+$ ]] \
  || ! [[ "$PROCESS_LIMIT" =~ ^[0-9]+$ ]]; then
  echo "ORCHESTRATOR=FAIL code=INVALID_EXPECTED_COUNT"
  exit 1
fi
if [ "$EXPECTED_TOTAL" -gt 0 ] && [ "$PROCESSED_BEFORE" -ge "$EXPECTED_TOTAL" ]; then
  echo "ORCHESTRATOR=FAIL code=INVALID_RESUME_OFFSET"
  exit 1
fi

mkdir -p corpus-data/batch-summaries corpus-data/chunks
rm -f corpus-data/input-manifest.jsonl h1-extraction.jsonl \
  h1-extraction-failures.jsonl h1-corpus-checkpoint.json \
  h1-quality-summary.json h1-corpus-summary.json
: > h1-extraction.jsonl
: > h1-extraction-failures.jsonl

tunnel_stop() {
  if [ -f "$WORK_DIR/ci-stunnel.pid" ]; then
    kill "$(cat "$WORK_DIR/ci-stunnel.pid")" 2>/dev/null || true
  fi
  for _ in $(seq 1 20); do
    if ! nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null \
      && ! nc -z 127.0.0.1 "$S3_LOCAL" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  rm -f "$WORK_DIR/ci-stunnel.pid"
  if nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null \
    || nc -z 127.0.0.1 "$S3_LOCAL" 2>/dev/null; then
    echo "TUNNEL_STOP=FAIL code=PORT_STILL_OPEN"
    return 1
  fi
  echo "TUNNEL_STOP=PASS"
}

tunnel_up() {
  bash scripts/ci/build_stunnel.sh
}

tunnel_restart() {
  tunnel_stop || return 1
  tunnel_up
}

overall=0
batch_no=0
total_downloaded=0
total_extracted=0
total_failures=0
total_pg_loaded=0
total_bytes=0
last_key="$CURSOR"
end_of_corpus=0
process_limit_reached=0

echo "H1_FULL_CONFIG batch_size=$BATCH_SIZE process_limit=$PROCESS_LIMIT expected_total=$EXPECTED_TOTAL processed_before=$PROCESSED_BEFORE"
if ! tunnel_up; then
  echo "ORCHESTRATOR=FAIL code=INITIAL_TUNNEL"
  exit 1
fi

while true; do
  batch_no=$((batch_no + 1))
  batch_name="$(printf '%06d' "$batch_no")"
  batch_dir="corpus-data/chunks/$batch_name"
  mkdir -p "$batch_dir"

  export CORPUS_OUTPUT_DIR="$batch_dir"
  export CORPUS_PREFIX="published/"
  request_limit="$BATCH_SIZE"
  if [ "$PROCESS_LIMIT" -gt 0 ]; then
    remaining_limit=$((PROCESS_LIMIT - total_downloaded))
    if [ "$remaining_limit" -le 0 ]; then
      process_limit_reached=1
      break
    fi
    if [ "$remaining_limit" -lt "$request_limit" ]; then
      request_limit="$remaining_limit"
    fi
  fi
  export CORPUS_LIMIT="$request_limit"
  export CORPUS_START_AFTER="$CURSOR"
  export CORPUS_INVENTORY_ONLY="0"

  echo "H1_BATCH_START index=$batch_no start_after=${CURSOR:-<BEGIN>}"
  if ! uv run python scripts/ci/h1_corpus_download.py; then
    echo "H1_BATCH_DOWNLOAD=FAIL index=$batch_no"
    overall=1
    break
  fi

  batch_summary="$batch_dir/batch-summary.json"
  if [ ! -f "$batch_summary" ]; then
    echo "H1_BATCH_DOWNLOAD=FAIL code=SUMMARY_MISSING index=$batch_no"
    overall=1
    break
  fi

  batch_meta="$(python3 - "$batch_summary" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("|".join(str(d.get(k, "")) for k in (
    "n_enumerated", "n_downloaded", "last_key", "end_of_corpus", "total_bytes"
)))
PY
)"
  IFS='|' read -r n_enumerated n_downloaded batch_last_key batch_end batch_bytes <<< "$batch_meta"

  if [ "$n_enumerated" = "0" ] && [ "$batch_end" = "True" ]; then
    echo "H1_FULL_END_OF_CORPUS after=$CURSOR"
    end_of_corpus=1
    rm -rf "$batch_dir"
    break
  fi
  if ! [[ "$n_enumerated" =~ ^[0-9]+$ ]] || [ "$n_enumerated" -eq 0 ]; then
    echo "H1_BATCH_DOWNLOAD=FAIL code=INVALID_BATCH_COUNT index=$batch_no"
    overall=1
    break
  fi
  if [ "$n_downloaded" != "$n_enumerated" ]; then
    echo "H1_BATCH_DOWNLOAD=FAIL code=PARTIAL_BATCH index=$batch_no enumerated=$n_enumerated downloaded=$n_downloaded"
    overall=1
    break
  fi
  if [ -z "$batch_last_key" ]; then
    echo "H1_BATCH_DOWNLOAD=FAIL code=LAST_KEY_MISSING index=$batch_no"
    overall=1
    break
  fi

  batch_h1="$batch_dir/h1-extraction.jsonl"
  batch_failures="$batch_dir/h1-extraction-failures.jsonl"
  if ! uv run nooshare-annual-semi-extraction h1-extract \
      --input-dir "$batch_dir/published" \
      --output "$batch_h1" \
      --failures "$batch_failures"; then
    echo "H1_BATCH_EXTRACT=FAIL index=$batch_no"
    overall=1
    break
  fi

  batch_extracted="$(wc -l < "$batch_h1" 2>/dev/null || echo 0)"
  batch_failure_count="$(wc -l < "$batch_failures" 2>/dev/null || echo 0)"
  if [ "$batch_extracted" != "$n_downloaded" ]; then
    echo "H1_BATCH_EXTRACT=FAIL code=ROW_COUNT_MISMATCH index=$batch_no downloaded=$n_downloaded extracted=$batch_extracted"
    overall=1
    break
  fi

  batch_validation="$batch_dir/input-validation.json"
  if ! uv run python scripts/ci/validate_h1_batch.py \
      --manifest "$batch_dir/input-manifest.jsonl" \
      --extraction "$batch_h1" \
      --output "$batch_validation"; then
    echo "H1_BATCH_INPUT_VALIDATION=FAIL index=$batch_no"
    overall=1
    break
  fi

  SQL_FILE="$WORK_DIR/h1_corpus_load_$batch_name.sql"
  if ! uv run python scripts/ci/h1_corpus_load_pg.py \
      --input "$batch_h1" --emit-csv "$SQL_FILE"; then
    echo "H1_BATCH_SQL=FAIL index=$batch_no"
    overall=1
    break
  fi

  # S3 reads consume the shared SNI-router connection slot. Tear down the
  # download tunnel and create a clean tunnel before the first PG connection.
  if ! tunnel_restart; then
    echo "PG_TUNNEL_REBUILD=FAIL index=$batch_no"
    overall=1
    break
  fi

  # P0 链路韧性：PG 写入失败后自动重试（最多 3 次）。
  # 安全保证：单事务回滚 + ON CONFLICT 幂等 + frp 1.7s 即恢复。
  # 根因：pro↔VPS 公网链路 frp 控制连接瞬断（Run #87 实据 0.3s 内三处日志互证）。
  pg_batch_ok=0
  pg_batch_attempts=0
  PG_BATCH_MAX_ATTEMPTS="${H1_PG_BATCH_MAX_ATTEMPTS:-3}"
  for pg_attempt in $(seq 1 "$PG_BATCH_MAX_ATTEMPTS"); do
    pg_batch_attempts=$pg_attempt
    if PGPASSWORD="${PG_PASSWORD:-}" psql -h 127.0.0.1 -p "$PG_LOCAL" -U ci_writer \
        -d nooshare_dev -v ON_ERROR_STOP=1 -f "$SQL_FILE" \
        >/dev/null 2>"$WORK_DIR/pg_load_err.txt"; then
      echo "PG_BATCH_LOAD=PASS index=$batch_no rows=$batch_extracted attempt=$pg_attempt"
      pg_batch_ok=1
      break
    fi
    echo "PG_BATCH_LOAD=RETRY index=$batch_no attempt=$pg_attempt/$PG_BATCH_MAX_ATTEMPTS"
    head -3 "$WORK_DIR/pg_load_err.txt" 2>/dev/null || true
    if [ "$pg_attempt" -lt "$PG_BATCH_MAX_ATTEMPTS" ]; then
      # 重建隧道后重试（frpc 断前无告警、1.7s 即重连成功，说明 VPS 侧活着）
      if ! tunnel_restart; then
        echo "PG_BATCH_TUNNEL_REBUILD=FAIL index=$batch_no attempt=$pg_attempt"
        break
      fi
      sleep 2
    fi
  done
  if [ "$pg_batch_ok" -ne 1 ]; then
    echo "PG_BATCH_LOAD=FAIL index=$batch_no attempts=$pg_batch_attempts"
    head -5 "$WORK_DIR/pg_load_err.txt" 2>/dev/null || true
    overall=1
    break
  fi
  rm -f "$SQL_FILE"

  # Only advance the resumable cursor after the PG transaction committed.
  if ! cat "$batch_dir/input-manifest.jsonl" >> corpus-data/input-manifest.jsonl; then
    echo "H1_BATCH_COMMIT=FAIL code=MANIFEST_APPEND index=$batch_no"
    overall=1
    break
  fi
  if ! cat "$batch_h1" >> h1-extraction.jsonl; then
    echo "H1_BATCH_COMMIT=FAIL code=RESULT_APPEND index=$batch_no"
    overall=1
    break
  fi
  if [ -s "$batch_failures" ] && ! cat "$batch_failures" >> h1-extraction-failures.jsonl; then
    echo "H1_BATCH_COMMIT=FAIL code=FAILURE_APPEND index=$batch_no"
    overall=1
    break
  fi

  python3 - "$batch_summary" "corpus-data/batch-summaries/$batch_name.json" \
      "$batch_extracted" "$batch_failure_count" <<'PY'
import json, sys
src, dst = sys.argv[1:3]
d = json.load(open(src, encoding="utf-8"))
d["n_extracted"] = int(sys.argv[3])
d["n_residuals"] = int(sys.argv[4])
d["pg_status"] = "PASS"
d["pg_loaded"] = int(sys.argv[3])
validation_path = src.replace("batch-summary.json", "input-validation.json")
d["input_validation"] = json.load(open(validation_path, encoding="utf-8"))
json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY

  total_downloaded=$((total_downloaded + n_downloaded))
  total_extracted=$((total_extracted + batch_extracted))
  total_failures=$((total_failures + batch_failure_count))
  total_pg_loaded=$((total_pg_loaded + batch_extracted))
  total_bytes=$((total_bytes + batch_bytes))
  CURSOR="$batch_last_key"
  last_key="$batch_last_key"

  if ! python3 - "h1-corpus-checkpoint.json" "$batch_no" "$CURSOR" \
      "$total_downloaded" "$total_extracted" "$total_failures" \
      "$total_pg_loaded" "$total_bytes" "$EXPECTED_TOTAL" "$PROCESSED_BEFORE" <<'PY'
import json, sys
keys = (
    "batch_no", "last_key", "downloaded", "extracted", "residuals",
    "pg_loaded", "bytes", "expected_total", "processed_before"
)
values = [sys.argv[i] if i == 3 else int(sys.argv[i]) for i in range(2, len(sys.argv))]
d = dict(zip(keys, values))
json.dump(d, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
  then
    echo "H1_BATCH_COMMIT=FAIL code=CHECKPOINT index=$batch_no"
    overall=1
    break
  fi

  echo "H1_BATCH_DONE index=$batch_no downloaded=$n_downloaded extracted=$batch_extracted residuals=$batch_failure_count total=$total_downloaded cursor=$CURSOR"

  # Free the runner disk before fetching the next group of source MD files.
  rm -rf "$batch_dir"

  if [ "$PROCESS_LIMIT" -gt 0 ] && [ "$total_downloaded" -ge "$PROCESS_LIMIT" ]; then
    process_limit_reached=1
    echo "H1_PROCESS_LIMIT_REACHED count=$total_downloaded"
    break
  fi

  if [ "$n_enumerated" -lt "$request_limit" ]; then
    end_of_corpus=1
    break
  fi

  if ! tunnel_restart; then
    echo "S3_TUNNEL_REBUILD=FAIL index=$batch_no"
    overall=1
    break
  fi
done

expected_remaining=0
expected_this_run=0
if [ "$EXPECTED_TOTAL" -gt 0 ]; then
  expected_remaining=$((EXPECTED_TOTAL - PROCESSED_BEFORE))
  expected_this_run="$expected_remaining"
  if [ "$PROCESS_LIMIT" -gt 0 ] && [ "$PROCESS_LIMIT" -lt "$expected_this_run" ]; then
    expected_this_run="$PROCESS_LIMIT"
  fi
fi

if [ "$overall" -eq 0 ] && [ "$EXPECTED_TOTAL" -gt 0 ] \
  && [ "$total_downloaded" -ne "$expected_this_run" ]; then
  echo "H1_FULL=FAIL code=EXPECTED_COUNT_MISMATCH expected=$expected_this_run actual=$total_downloaded"
  overall=1
fi
if [ "$total_downloaded" -ne "$total_extracted" ] \
  || [ "$total_extracted" -ne "$total_pg_loaded" ]; then
  echo "H1_FULL=FAIL code=END_TO_END_COUNT_MISMATCH downloaded=$total_downloaded extracted=$total_extracted pg=$total_pg_loaded"
  overall=1
fi

if [ -f h1-extraction.jsonl ]; then
  if ! uv run python scripts/ci/summarize_h1_corpus.py \
      --input h1-extraction.jsonl \
      --failures h1-extraction-failures.jsonl \
      --expected "$expected_this_run" \
      --output h1-quality-summary.json; then
    echo "H1_ACCOUNTING_SUMMARY=FAIL"
    overall=1
  fi
fi

pg_reconcile_status="NOT_REQUESTED"
pg_reconcile_rows=0
pg_reconcile_unique_slots=0
pg_reconcile_duplicate_slots=0
pg_reconcile_missing_sha=0
pg_reconcile_invalid_sha=0

if [ "${H1_VERIFY_PG_CORPUS:-0}" = "1" ]; then
  completed_total=$((PROCESSED_BEFORE + total_downloaded))
  if [ "$overall" -ne 0 ] || [ "$EXPECTED_TOTAL" -le 0 ] || [ "$completed_total" -ne "$EXPECTED_TOTAL" ]; then
    pg_reconcile_status="SKIPPED_INCOMPLETE"
    echo "PG_RECONCILIATION=SKIPPED code=CORPUS_NOT_COMPLETE completed=$completed_total expected=$EXPECTED_TOTAL"
  else
    echo "PG_RECONCILIATION=start expected_rows=$EXPECTED_TOTAL"
    query="SELECT COUNT(*)::bigint, COUNT(DISTINCT slot_key)::bigint, COUNT(*) FILTER (WHERE source_sha256 IS NULL)::bigint, COUNT(*) FILTER (WHERE source_sha256 !~ '^[0-9a-f]{64}$')::bigint FROM annual_semi.h1_corpus_results;"
    pg_counts="$(PGPASSWORD="${PG_PASSWORD:-}" psql -h 127.0.0.1 -p "$PG_LOCAL" -U ci_writer -d nooshare_dev -A -t -F ',' -v ON_ERROR_STOP=1 -c "$query" 2>"$WORK_DIR/pg_reconciliation_err.txt")"
    pg_rc=$?
    if [ "$pg_rc" -ne 0 ]; then
      pg_reconcile_status="FAIL"
      echo "PG_RECONCILIATION=FAIL code=QUERY_FAILED"
      head -5 "$WORK_DIR/pg_reconciliation_err.txt" 2>/dev/null || true
      overall=1
    else
      IFS=',' read -r pg_reconcile_rows pg_reconcile_unique_slots pg_reconcile_missing_sha pg_reconcile_invalid_sha <<< "$pg_counts"
      pg_reconcile_rows="${pg_reconcile_rows//[[:space:]]/}"
      pg_reconcile_unique_slots="${pg_reconcile_unique_slots//[[:space:]]/}"
      pg_reconcile_missing_sha="${pg_reconcile_missing_sha//[[:space:]]/}"
      pg_reconcile_invalid_sha="${pg_reconcile_invalid_sha//[[:space:]]/}"
      if ! [[ "$pg_reconcile_rows" =~ ^[0-9]+$ ]] || ! [[ "$pg_reconcile_unique_slots" =~ ^[0-9]+$ ]] || ! [[ "$pg_reconcile_missing_sha" =~ ^[0-9]+$ ]] || ! [[ "$pg_reconcile_invalid_sha" =~ ^[0-9]+$ ]]; then
        pg_reconcile_status="FAIL"
        echo "PG_RECONCILIATION=FAIL code=INVALID_QUERY_RESULT"
        overall=1
      else
        pg_reconcile_duplicate_slots=$((pg_reconcile_rows - pg_reconcile_unique_slots))
        if [ "$pg_reconcile_rows" -eq "$EXPECTED_TOTAL" ] && [ "$pg_reconcile_unique_slots" -eq "$EXPECTED_TOTAL" ] && [ "$pg_reconcile_missing_sha" -eq 0 ] && [ "$pg_reconcile_invalid_sha" -eq 0 ]; then
          pg_reconcile_status="PASS"
          echo "PG_RECONCILIATION=PASS rows=$pg_reconcile_rows distinct_slots=$pg_reconcile_unique_slots duplicates=$pg_reconcile_duplicate_slots missing_sha=$pg_reconcile_missing_sha invalid_sha=$pg_reconcile_invalid_sha"
        else
          pg_reconcile_status="FAIL"
          echo "PG_RECONCILIATION=FAIL rows=$pg_reconcile_rows distinct_slots=$pg_reconcile_unique_slots duplicates=$pg_reconcile_duplicate_slots missing_sha=$pg_reconcile_missing_sha invalid_sha=$pg_reconcile_invalid_sha expected=$EXPECTED_TOTAL"
          overall=1
        fi
      fi
    fi
  fi
fi

cat > h1-corpus-summary.json <<EOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "mode": "full_h1_chunked",
  "bucket": "annual-semi",
  "prefix": "published/",
  "expected_total": $EXPECTED_TOTAL,
  "expected_this_run": $expected_this_run,
  "processed_before": $PROCESSED_BEFORE,
  "batch_size": $BATCH_SIZE,
  "process_limit": $PROCESS_LIMIT,
  "process_limit_reached": $process_limit_reached,
  "n_batches": $batch_no,
  "n_downloaded": $total_downloaded,
  "n_extracted": $total_extracted,
  "n_failures": $total_failures,
  "pg_loaded": $total_pg_loaded,
  "total_bytes": $total_bytes,
  "last_key": "$last_key",
  "end_of_corpus": $end_of_corpus,
  "pg_reconciliation_status": "$pg_reconcile_status",
  "pg_reconciliation_rows": $pg_reconcile_rows,
  "pg_reconciliation_distinct_slots": $pg_reconcile_unique_slots,
  "pg_reconciliation_duplicate_slots": $pg_reconcile_duplicate_slots,
  "pg_reconciliation_missing_sha": $pg_reconcile_missing_sha,
  "pg_reconciliation_invalid_sha": $pg_reconcile_invalid_sha,
  "overall_status": $([ "$overall" -eq 0 ] && echo '"PASS"' || echo '"FAIL"')
}
EOF

echo "H1_FULL_SUMMARY written batches=$batch_no downloaded=$total_downloaded extracted=$total_extracted pg_loaded=$total_pg_loaded bytes=$total_bytes"

bash scripts/ci/leak_check.sh "$AUDIT" || overall=1
if [ "$overall" -eq 0 ]; then
  echo "ORCHESTRATOR=PASS"
else
  echo "ORCHESTRATOR=FAIL code=H1_FULL_FAILED"
fi
exit "$overall"
