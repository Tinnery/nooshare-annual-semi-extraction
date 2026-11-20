#!/usr/bin/env bash
# PG 真连探针（经 stunnel 本地端口）。断言式：版本号 + 模板库行数。
# 失败只输出错误码，绝不 cat 原始错误（可能含连接串/密码）。
set -uo pipefail

AUDIT="${RUNNER_TEMP:-/tmp}/ci_audit.log"
# PG 连接参数全部为固定常量（非敏感）：端点/库/只读 role。仅密码走 secret 通道。
# 不信任任何外部注入的 host/port/db/user——误填会导致 DNS_FAIL/DB_MISSING/ROLE_MISSING。
PG_HOST="127.0.0.1"
PG_PORT="${PG_LOCAL_PORT:-15432}"
PG_DB="nooshare_dev"
PG_USER="ci_probe"
if [ -z "${PG_PASSWORD:-}" ]; then
  echo "PG_PROBE=FAIL code=PG_SECRET_MISSING" | tee -a "$AUDIT"
  exit 1
fi
OUT="${RUNNER_TEMP:-/tmp}/pg_result.txt"
ERR="${RUNNER_TEMP:-/tmp}/pg_err.txt"

PGPASSWORD="$PG_PASSWORD" psql \
  -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  -tAc "SELECT current_setting('server_version'), (SELECT count(*) FROM annual_semi.h1_pattern_library);" \
  > "$OUT" 2> "$ERR"
rc=$?

result=1
if [ "$rc" -eq 0 ]; then
  # psql -tAc 用 | 分隔多列（如 "18.1|52"），不是空白分隔
  IFS='|' read -r version cnt < "$OUT"
  version=$(printf '%s' "$version" | tr -d '[:space:]')
  cnt=$(printf '%s' "$cnt" | tr -d '[:space:]')
  # 断言：版本号形如 18.1；行数 > 0
  if [[ "$version" =~ ^[0-9]+\.[0-9]+ ]] && [[ "$cnt" =~ ^[0-9]+$ ]] && [ "$cnt" -gt 0 ]; then
    echo "PG_PROBE=PASS version=$version patterns=$cnt" | tee -a "$AUDIT"
    result=0
  else
    echo "PG_PROBE=FAIL code=PG_ASSERT" | tee -a "$AUDIT"
  fi
else
  # 只按关键词映射为固定枚举码，绝不回显原始错误（可能含 DSN/密码）
  code="PG_CONN_${rc}"
  if grep -qi "password authentication failed" "$ERR" 2>/dev/null; then
    code="PG_AUTH_FAIL"
  elif grep -qi "server closed the connection\|unexpected eof" "$ERR" 2>/dev/null; then
    code="PG_TUNNEL_DROP"
  elif grep -qi "could not translate host\|Name or service not known\|temporary failure in name resolution" "$ERR" 2>/dev/null; then
    code="PG_DNS_FAIL"
  elif grep -qi "connection refused" "$ERR" 2>/dev/null; then
    code="PG_TCP_REFUSED"
  elif grep -qi "could not connect to server\|timeout\|timed out" "$ERR" 2>/dev/null; then
    code="PG_CONN_TIMEOUT"
  elif grep -qi "no pg_hba.conf entry" "$ERR" 2>/dev/null; then
    code="PG_HBA_DENY"
  elif grep -qi "database .* does not exist" "$ERR" 2>/dev/null; then
    code="PG_DB_MISSING"
  elif grep -qiE "role .* does not exist|role \".*\" does not exist" "$ERR" 2>/dev/null; then
    code="PG_ROLE_MISSING"
  elif grep -qi "relation .* does not exist\|permission denied" "$ERR" 2>/dev/null; then
    code="PG_PERM_OR_RELATION"
  elif grep -qi "schema .* does not exist" "$ERR" 2>/dev/null; then
    code="PG_SCHEMA_MISSING"
  elif grep -qi "function .* does not exist" "$ERR" 2>/dev/null; then
    code="PG_FUNCTION_MISSING"
  elif grep -qi "does not exist" "$ERR" 2>/dev/null; then
    # 提取 "X does not exist" 中 X 的类型词（仅结构词，不含对象名/密钥）
    obj=$(grep -oiE "[a-z_]+ does not exist" "$ERR" 2>/dev/null | head -1 | awk '{print $1}')
    code="PG_NOTEXIST_${obj:-unknown}"
  fi
  echo "PG_RC=$rc" | tee -a "$AUDIT"
  echo "PG_PROBE=FAIL code=$code" | tee -a "$AUDIT"
fi

# 立即清洗临时文件（含查询结果，虽非敏感但保持整洁）
shred -u "$OUT" "$ERR" 2>/dev/null || rm -f "$OUT" "$ERR"

exit "$result"
