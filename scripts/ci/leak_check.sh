#!/usr/bin/env bash
# 不泄露主动证伪：对每个 secret 值做 raw/hex/base64/url 四编码 grep。
# 命中数必须全为 0。仅使用已注入的环境变量值，不读任何落盘明文。
#
# 架构说明：CI 使用单个 JSON secret（NOOSHARE_INFRA），workflow 的 run: 块
# 用 jq 解析后 export 为独立环境变量。本脚本作为子进程继承这些 export，
# 因此检查各个独立变量即可覆盖所有敏感值。
set -uo pipefail

LOG_FILE="${1:-}"

if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
  echo "LEAK_CHECK=SKIP reason=no_log"
  exit 0
fi

fail=0

check_value() {
  local label="$1" value="$2"
  [ -z "$value" ] && return 0
  local enc_hex enc_b64 enc_url
  enc_hex=$(printf '%s' "$value" | od -An -tx1 | tr -d ' \n')
  enc_b64=$(printf '%s' "$value" | base64 -w0 2>/dev/null)
  enc_url=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$value" 2>/dev/null)
  for enc in "$value" "$enc_hex" "$enc_b64" "$enc_url"; do
    [ -z "$enc" ] && continue
    local n
    n=$(grep -Foc "$enc" "$LOG_FILE" 2>/dev/null || true)
    if [ "${n:-0}" -ne 0 ]; then
      echo "LEAK_DETECTED label=$label hits=$n"
      fail=1
    fi
  done
}

# 所有 secret 值（从环境变量读，不落盘）
# 这些变量由 workflow 的 run: 块从 NOOSHARE_INFRA JSON 解析后 export
for name in PG_PASSWORD RUSTFS_ACCESS_KEY RUSTFS_SECRET_KEY STUNNEL_PSK STUNNEL_HOST; do
  check_value "$name" "${!name:-}"
done

if [ "$fail" -eq 0 ]; then
  echo "LEAK_CHECK=PASS"
else
  echo "LEAK_CHECK=FAIL"
fi
exit "$fail"
