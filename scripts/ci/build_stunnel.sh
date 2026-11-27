#!/usr/bin/env bash
# 从 GitHub Secrets（注入为环境变量）动态生成 stunnel 客户端配置。
# 拓扑依据（已验证的 pro 侧模板）：单一 SNI router 入口（地址由 STUNNEL_HOST 注入），
#   靠 TLS SNI（客户端 sni=）分流 pg.noos.com / rustfs.noos.com。
#   根因：protocolHost= 不设置 TLS SNI（仅用于 proxy CONNECT 协商），会落到默认端口导致失败。
# 脚本本身不含任何实值；临时文件权限 600，随 job 销毁。
set -euo pipefail

: "${STUNNEL_HOST:?STUNNEL_HOST secret missing}"
: "${STUNNEL_PSK:?STUNNEL_PSK secret missing}"

WORK_DIR="${RUNNER_TEMP:-/tmp}"
umask 077

# ---- 自适应解析 STUNNEL_HOST ----
# 含 ":" → host:port；否则只当 host，端口取 STUNNEL_PORT 或 SNI router 默认 27002。
if [[ "$STUNNEL_HOST" == *:* ]]; then
  RELAY_HOST="${STUNNEL_HOST%%:*}"
  RELAY_PORT="${STUNNEL_HOST##*:}"
else
  RELAY_HOST="$STUNNEL_HOST"
  RELAY_PORT="${STUNNEL_PORT:-27002}"
fi

# ---- 自适应解析 STUNNEL_PSK ----
# 格式 identity:hex → 直接写；纯 hex → 用模板 identity "k1"。
PSK_FILE="$WORK_DIR/ci-psk.txt"
if [[ "$STUNNEL_PSK" == *:* ]]; then
  printf '%s\n' "$STUNNEL_PSK" > "$PSK_FILE"
else
  printf 'k1:%s\n' "$STUNNEL_PSK" > "$PSK_FILE"
fi

# ---- 本地监听端口（PG_PROBE 连 15432；S3_PROBE 连 15500）----
PG_LOCAL="${PG_LOCAL_PORT:-15432}"
S3_LOCAL="${S3_LOCAL_PORT:-15500}"

CONF="$WORK_DIR/ci-stunnel.conf"
cat > "$CONF" <<EOF
foreground = yes
pid =
debug = 7
output = ${WORK_DIR}/dev-market-data-stunnel.log
sslVersionMin = TLSv1.2

; PostgreSQL —— SNI router 分流到 pro 的 PG 5432
; 关键：用 sni= 发 TLS SNI（protocolHost 不设 SNI，会导致落到默认端口而失败）
[pg]
client = yes
accept = 127.0.0.1:${PG_LOCAL}
connect = ${RELAY_HOST}:${RELAY_PORT}
sni = pg.noos.com
ciphers = PSK
PSKsecrets = ${PSK_FILE}

; RustFS —— SNI router 分流到 pro 的 RustFS 9000
[rustfs]
client = yes
accept = 127.0.0.1:${S3_LOCAL}
connect = ${RELAY_HOST}:${RELAY_PORT}
sni = rustfs.noos.com
ciphers = PSK
PSKsecrets = ${PSK_FILE}
EOF

chmod 600 "$CONF" "$PSK_FILE"
echo "STUNNEL_CONF=$CONF"
echo "RELAY_ENDPOINT=${RELAY_HOST}:${RELAY_PORT} (SNI router)"
echo "RELAY_PORT_VALUE=${RELAY_PORT}"
echo "PG_LOCAL=$PG_LOCAL"
echo "S3_LOCAL=$S3_LOCAL"

# 启动隧道：nohup + </dev/null 使其脱离父 shell 的 stdin/管道，
# 否则子 shell 退出时 foreground stunnel 会因管道关闭而退出（表现为随后 PG_LOCAL_REFUSED）。
nohup stunnel "$CONF" </dev/null >/dev/null 2>&1 &
echo $! > "$WORK_DIR/ci-stunnel.pid"

# 等待本地端口就绪
ready=1
for i in $(seq 1 30); do
  nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null && break
  sleep 0.5
done
nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null && echo "TUNNEL_PG_READY=1" || { echo "TUNNEL_PG_FAIL=code_TPG1"; ready=0; }
for i in $(seq 1 30); do
  nc -z 127.0.0.1 "$S3_LOCAL" 2>/dev/null && break
  sleep 0.5
done
nc -z 127.0.0.1 "$S3_LOCAL" 2>/dev/null && echo "TUNNEL_S3_READY=1" || { echo "TUNNEL_S3_FAIL=code_TS3_1"; ready=0; }

[ "$ready" -eq 1 ]
