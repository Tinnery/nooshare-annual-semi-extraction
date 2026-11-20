#!/usr/bin/env bash
# 隧道清理：杀 stunnel、shred 临时文件、确认端口关闭。
set -uo pipefail
WORK_DIR="${RUNNER_TEMP:-/tmp}"

if [ -f "$WORK_DIR/ci-stunnel.pid" ]; then
  kill "$(cat "$WORK_DIR/ci-stunnel.pid")" 2>/dev/null || true
fi
shred -u "$WORK_DIR/ci-stunnel.conf" "$WORK_DIR/ci-psk.txt" 2>/dev/null \
  || rm -f "$WORK_DIR/ci-stunnel.conf" "$WORK_DIR/ci-psk.txt"
rm -f "$WORK_DIR/ci-stunnel.pid"

PG_LOCAL="${PG_LOCAL_PORT:-15432}"
S3_LOCAL="${S3_LOCAL_PORT:-15500}"
if nc -z 127.0.0.1 "$PG_LOCAL" 2>/dev/null || nc -z 127.0.0.1 "$S3_LOCAL" 2>/dev/null; then
  echo "TEARDOWN=FAIL code=PORT_OPEN"
  exit 1
fi
echo "TEARDOWN=PASS"
