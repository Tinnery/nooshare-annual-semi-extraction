#!/usr/bin/env bash
# 统一编排：隧道 + 双探针 + 泄露检测 + 清理，全部在同一 CI step 生命周期内。
#
# 根因背景：GitHub Actions 每个 `run:` step 是独立 shell，step 结束会回收其派生的
# 后台进程。若 build_stunnel.sh 单独成 step，stunnel 在探针 step 开始时已被清理，
# 导致 psql 连本地端口得到 connection refused（PG_LOCAL_REFUSED），而隧道其实曾就绪。
# 因此必须把隧道与所有依赖它的探针放在同一 step，并用 trap 保证清理。
set -uo pipefail

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

# 1b) 存活复检：确认隧道在 build 脚本退出后仍然监听（区分"step 杀进程"vs"连接细节"）
PG_LOCAL_PORT_CHECK="${PG_LOCAL_PORT:-15432}"
S3_LOCAL_PORT_CHECK="${S3_LOCAL_PORT:-15500}"
if nc -z 127.0.0.1 "$PG_LOCAL_PORT_CHECK" 2>/dev/null; then
  echo "TUNNEL_PG_ALIVE_AFTER_BUILD=1"
else
  echo "TUNNEL_PG_ALIVE_AFTER_BUILD=0"
fi
if nc -z 127.0.0.1 "$S3_LOCAL_PORT_CHECK" 2>/dev/null; then
  echo "TUNNEL_S3_ALIVE_AFTER_BUILD=1"
else
  echo "TUNNEL_S3_ALIVE_AFTER_BUILD=0"
fi

# 2) PG 探针（失败不中断其余步骤，继续采集诊断）
bash scripts/ci/probe_pg.sh || overall=1

# 3) RustFS 探针
python3 scripts/ci/probe_s3.py || overall=1

# 4) 独立重建隧道；iwen 数据读取必须占用新隧道的首个 PG 会话。
bash scripts/ci/teardown.sh || overall=1
if bash scripts/ci/build_stunnel.sh; then
  if nc -z 127.0.0.1 "${PG_LOCAL_PORT:-15432}" 2>/dev/null; then
    bash scripts/ci/export_iwen_limit_up.sh || overall=1
  else
    echo "PG_IWEN_EXPORT=FAIL code=PG_IWEN_TUNNEL_NOT_LISTENING"
    overall=1
  fi
else
  echo "PG_IWEN_EXPORT=FAIL code=PG_IWEN_TUNNEL_REBUILD"
  overall=1
fi
bash scripts/ci/teardown.sh || overall=1

# 4) 泄露证伪（始终检查审计日志）
bash scripts/ci/leak_check.sh "$AUDIT" || overall=1

if [ "$overall" -eq 0 ]; then
  echo "ORCHESTRATOR=PASS"
else
  echo "ORCHESTRATOR=FAIL code=PROBE_FAILED"
fi
exit "$overall"
