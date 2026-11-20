#!/usr/bin/env bash
# H2 语料批量抽取流程：隧道 + 下载 + H2 抽取 + 摘要。
#
# 职责边界（窄）：
# - 只消费已发布的语料（published/ 前缀）
# - 抽取"第二节"完整内容
# - 不连接 PG / 不写入数据库（H2 暂不需要 PG 持久化）
# - 产出：corpus-data/ 目录（含 MD 文件、batch-summary.json）
#        h2-extraction.jsonl（H2 抽取结果）
#        h2-corpus-summary.json（最终批次摘要）
set -uo pipefail

WORK_DIR="${RUNNER_TEMP:-/tmp}"
AUDIT="$WORK_DIR/ci_audit.log"
rm -f "$AUDIT"

cleanup() {
  bash scripts/ci/teardown.sh
}
trap cleanup EXIT

overall=0

# 1) 建立隧道
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

# 2) 语料下载（复用 H1 的下载脚本，支持分层随机采样）
export CORPUS_OUTPUT_DIR="corpus-data"
export CORPUS_PREFIX="published/"
export CORPUS_LIMIT="${H2_CORPUS_LIMIT:-10}"  # 默认 10 个样本

if ! uv run python scripts/ci/h1_corpus_download.py; then
  echo "CORPUS_DOWNLOAD=FAIL"
  overall=1
fi

# 3) H2 抽取（如果下载成功）
n_extracted=0
n_found=0
n_not_found=0
n_errors=0
if [ "$overall" -eq 0 ]; then
  echo "H2_EXTRACT start"
  
  if ! uv run nooshare-annual-semi-extraction h2-extract \
      --input-dir "corpus-data/published" \
      --output "h2-extraction.jsonl" \
      --failures "h2-extraction-failures.jsonl"; then
    echo "H2_EXTRACT=FAIL"
    overall=1
  else
    echo "H2_EXTRACT=PASS"
    
    # 统计抽取结果
    n_extracted=$(wc -l < h2-extraction.jsonl 2>/dev/null || echo 0)
    n_not_found=$(wc -l < h2-extraction-failures.jsonl 2>/dev/null || echo 0)
    
    # 统计找到第二节的数量
    if [ -f h2-extraction.jsonl ]; then
      n_found=$(grep -c '"h2_found": true' h2-extraction.jsonl 2>/dev/null || echo 0)
    fi
    
    echo "H2_EXTRACTED=$n_extracted"
    echo "H2_FOUND=$n_found"
    echo "H2_NOT_FOUND=$n_not_found"
  fi
fi

# 4) 生成最终批次摘要
cat > h2-corpus-summary.json <<EOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "mode": "h2_extract",
  "corpus_output_dir": "corpus-data",
  "h2_extraction_file": "h2-extraction.jsonl",
  "h2_extraction_failures": "h2-extraction-failures.jsonl",
  "n_extracted": ${n_extracted:-0},
  "n_found": ${n_found:-0},
  "n_not_found": ${n_not_found:-0},
  "n_errors": ${n_errors:-0},
  "overall_status": $([ "$overall" -eq 0 ] && echo '"PASS"' || echo '"FAIL"')
}
EOF

echo "H2_CORPUS_SUMMARY written to h2-corpus-summary.json"

# 5) 泄露证伪
bash scripts/ci/leak_check.sh "$AUDIT" || overall=1

if [ "$overall" -eq 0 ]; then
  echo "ORCHESTRATOR=PASS"
else
  echo "ORCHESTRATOR=FAIL code=H2_CORPUS_FAILED"
fi
exit "$overall"
