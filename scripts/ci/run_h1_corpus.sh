#!/usr/bin/env bash
# H1 语料批量生产流程编排：隧道 + 下载 + 抽取 + 摘要，全部在同一 CI step 生命周期内。
#
# 职责边界（窄）：
# - 只消费已发布的语料（published/ 前缀）
# - 不执行上游 MD 完整性检查
# - 不连接 PG / 不写入数据库
# - 产出：corpus-data/ 目录（含 MD 文件、input-manifest.jsonl、batch-summary.json）
#        h1-extraction.jsonl（H1 抽取结果）
#        h1-corpus-summary.json（最终批次摘要）
#
# 与 run_probes.sh 的区别：
# - run_probes.sh：验证基础设施连通性（canary 往返）
# - run_h1_corpus.sh：生产研究数据（批量读取 + 抽取）
set -uo pipefail

# Full-corpus mode owns its own tunnel lifecycle, chunk cleanup, and checkpointing.
if [ "${H1_CORPUS_FULL:-0}" = "1" ]; then
  exec bash scripts/ci/run_h1_corpus_full.sh
fi

WORK_DIR="${RUNNER_TEMP:-/tmp}"
AUDIT="$WORK_DIR/ci_audit.log"
rm -f "$AUDIT"

cleanup() {
  bash scripts/ci/teardown.sh
}
trap cleanup EXIT

overall=0

# 1) 建立隧道（stunnel 处于本 step 进程组，探针阶段仍存活）
if ! bash scripts/ci/build_stunnel.sh; then
  echo "ORCHESTRATOR=FAIL code=TUNNEL_BUILD"
  exit 1
fi

# 1b) 存活复检
S3_LOCAL_PORT_CHECK="${S3_LOCAL_PORT:-15500}"
if nc -z 127.0.0.1 "$S3_LOCAL_PORT_CHECK" 2>/dev/null; then
  echo "TUNNEL_S3_ALIVE_AFTER_BUILD=1"
else
  echo "TUNNEL_S3_ALIVE_AFTER_BUILD=0"
fi

# 2) 导出权威报告清单（PG 读，隧道刚建立、连接配额充足）
# 清单来自 annual_semi.reconciled_report，作为下载的白名单。
export CORPUS_OUTPUT_DIR="corpus-data"
if ! uv run python scripts/ci/h1_report_list_export.py; then
  echo "REPORT_LIST_EXPORT=FAIL"
  overall=1
fi
export REPORT_LIST_PATH="corpus-data/report-list.jsonl"

# 3) 语料下载（仅清单内的报告）
export CORPUS_PREFIX="published/"
export CORPUS_LIMIT="${H1_CORPUS_LIMIT:-0}"  # 0 = 不限制

if [ "$overall" -eq 0 ] && ! uv run python scripts/ci/h1_corpus_download.py; then
  echo "CORPUS_DOWNLOAD=FAIL"
  overall=1
fi

# 4) H1 抽取（如果下载成功）
if [ "${CORPUS_INVENTORY_ONLY:-0}" = "1" ] && [ "$overall" -eq 0 ]; then
  echo "H1_EXTRACT=SKIPPED_INVENTORY_ONLY"
fi
n_extracted=0
n_failures=0
if [ "$overall" -eq 0 ] && [ "${CORPUS_INVENTORY_ONLY:-0}" != "1" ]; then
  echo "H1_EXTRACT start"
  
  # 使用 uv run 调用 h1-extract CLI
  if ! uv run nooshare-annual-semi-extraction h1-extract \
      --input-dir "corpus-data/published" \
      --output "h1-extraction.jsonl" \
      --failures "h1-extraction-failures.jsonl"; then
    echo "H1_EXTRACT=FAIL"
    overall=1
  else
    echo "H1_EXTRACT=PASS"
    
    # 统计抽取结果
    n_extracted=$(wc -l < h1-extraction.jsonl 2>/dev/null || echo 0)
    n_failures=$(wc -l < h1-extraction-failures.jsonl 2>/dev/null || echo 0)
    echo "H1_EXTRACTED=$n_extracted"
    echo "H1_FAILURES=$n_failures"

    # 隧道重建前生成 SQL（纯本地操作，不连 PG）。
    # 这样重建后第一次 PG 连接直接用于写入，不浪费在探针或 python 子进程上。
    SQL_FILE="$WORK_DIR/h1_corpus_load.sql"
    if ! uv run python scripts/ci/h1_corpus_load_pg.py \
        --input h1-extraction.jsonl --emit-sql "$SQL_FILE"; then
      echo "SQL_EMIT=FAIL"
      overall=1
    fi
  fi
fi

# 5) PG 写入（如果抽取成功且有 PG_PASSWORD）
pg_loaded=0
pg_skipped=0
pg_status="SKIPPED"
if [ "$overall" -eq 0 ] && [ -n "${PG_PASSWORD:-}" ] && [ -f h1-extraction.jsonl ]; then
  echo "PG_LOAD start"
  PG_LOCAL="${PG_LOCAL_PORT:-15432}"

  # 根因（已实测）：S3 下载（boto3 并发连接）占满 SNI router 对同一 PSK identity
  # 的连接配额，导致同一 stunnel 进程内 PG 段无法再建新连接
  # —— 下载前 psql PASS、下载后 FAIL，但 TCP 端口仍 ALIVE。
  # 修复：PG 写入前重建隧道，关闭旧连接释放 router 配额，再建干净隧道。
  echo "PG_TUNNEL_REBUILD start"
  if [ -f "$WORK_DIR/ci-stunnel.pid" ]; then
    kill "$(cat "$WORK_DIR/ci-stunnel.pid")" 2>/dev/null || true
  fi
  # 等待旧隧道端口释放（最多 10s）
  for i in $(seq 1 20); do
    nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null || break
    sleep 0.5
  done
  if nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null; then
    echo "PG_TUNNEL_REBUILD=FAIL code=PORT_STILL_OPEN"
    pg_status="FAIL"
    overall=1
  elif ! bash scripts/ci/build_stunnel.sh; then
    echo "PG_TUNNEL_REBUILD=FAIL code=BUILD_FAIL"
    pg_status="FAIL"
    overall=1
  else
    echo "PG_TUNNEL_REBUILD=PASS"
    if [ "$overall" -eq 0 ]; then
      # 关键：不在写入前做 psql 探针。
      # 实测探针会消耗 router 重建后唯一的可用连接槽，导致紧随的写入连接被关闭。
      # SQL 生成放在隧道重建前（不连 PG），重建后第一次 PG 连接直接用于写入。
      SQL_FILE="$WORK_DIR/h1_corpus_load.sql"
      if PGPASSWORD="$PG_PASSWORD" psql -h 127.0.0.1 -p "$PG_LOCAL" -U ci_writer \
          -d nooshare_dev -v ON_ERROR_STOP=1 -f "$SQL_FILE" >/dev/null 2>"$WORK_DIR/pg_load_err.txt"; then
        pg_loaded="$n_extracted"
        pg_status="PASS"
        echo "PG_LOAD=PASS rows_written=$pg_loaded"
      else
        echo "PG_LOAD=FAIL (psql -f)"
        head -5 "$WORK_DIR/pg_load_err.txt" 2>/dev/null || true
        pg_status="FAIL"
        overall=1
      fi
    fi
  fi
fi

# 6) 生成最终批次摘要
cat > h1-corpus-summary.json <<EOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "mode": "$([ "${CORPUS_INVENTORY_ONLY:-0}" = "1" ] && echo 'inventory_only' || echo 'h1_extract')",
  "corpus_output_dir": "corpus-data",
  "h1_extraction_file": "h1-extraction.jsonl",
  "h1_extraction_failures": "h1-extraction-failures.jsonl",
  "n_extracted": ${n_extracted:-0},
  "n_failures": ${n_failures:-0},
  "pg_status": "${pg_status}",
  "pg_loaded": ${pg_loaded:-0},
  "pg_skipped": ${pg_skipped:-0},
  "overall_status": $([ "$overall" -eq 0 ] && echo '"PASS"' || echo '"FAIL"')
}
EOF

echo "H1_CORPUS_SUMMARY written to h1-corpus-summary.json"

# 7) 泄露证伪（始终检查审计日志）
bash scripts/ci/leak_check.sh "$AUDIT" || overall=1

if [ "$overall" -eq 0 ]; then
  echo "ORCHESTRATOR=PASS"
else
  echo "ORCHESTRATOR=FAIL code=H1_CORPUS_FAILED"
fi
exit "$overall"
