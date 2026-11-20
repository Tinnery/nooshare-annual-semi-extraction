"""win <-> pro 本 repo 目录同步（pro 目录不是 git 仓库，以 win 的 git HEAD 为准）。

背景：历史上靠手工 scp 挑文件，漏掉 extractor.py 导致 pro 跑旧版抽取逻辑。
本工具用 git ls-files 作为权威清单，全量打包传输 + sha256sum -c 逐文件校验。

同步范围（win -> pro）：git 跟踪的所有文件，**排除 data/**（运行产物，pro 上
才是最新的，不能被 win 的历史版本覆盖）。
不同步：.git / .venv / __pycache__ / .pytest_cache / *.pyc（本就不在 git 里）。

用法：
    python scripts/sync_matrix.py --check          # 只读差异报告
    python scripts/sync_matrix.py                 # win -> pro 同步 + 校验
    python scripts/sync_matrix.py --pull-results  # 同步后把 pro 成果拉回 win
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "travis@192.168.31.233"
RROOT = "/home/travis/repos/nooshare-annual-semi-extraction"
MANIFEST = ".sync_manifest.txt"
TARBALL = ROOT / "data" / ".repo_sync.tar.gz"

# pro 上运行产出的最新成果，win 侧可能是旧版或缺失
RESULT_FILES = [
    "data/h1_combo_raw.json",
    "data/h1_combo_raw_docs.jsonl",
    "data/library_coverage_2021plus.json",
]


def sh(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, **kw)


def git_files() -> list[str]:
    r = sh(["git", "ls-files", "-z"])
    r.check_returncode()
    return [f.decode("utf-8") for f in r.stdout.split(b"\0") if f]


def sync_files() -> list[str]:
    return [n for n in git_files() if not n.startswith("data/")]


def remote_file_list() -> list[str]:
    cmd = (f"cd {RROOT} && find . -type f "
           "-not -path './.venv/*' -not -path '*/__pycache__/*' "
           "-not -path './.pytest_cache/*' -not -path './data/*' "
           "-not -name '*.pyc' -printf '%P\\n' | sort")
    r = sh(["ssh", REMOTE, cmd])
    if r.returncode != 0:
        print(f"远端列文件失败: {r.stderr.decode('utf-8', 'replace')[:300]}",
              file=sys.stderr)
        return []
    return [x for x in r.stdout.decode("utf-8", "replace").splitlines() if x]


def check() -> int:
    win = set(sync_files())
    pro = set(remote_file_list())
    only_win = sorted(win - pro)
    only_pro = sorted(pro - win)
    print(f"win git 跟踪(非 data): {len(win)} | pro 实际文件(非 data): {len(pro)}")
    print(f"\n=== 仅 win 有（将推送到 pro）: {len(only_win)} 个 ===")
    for n in only_win[:60]:
        print(f"  + {n}")
    if len(only_win) > 60:
        print(f"  ... 另有 {len(only_win) - 60} 个")
    print(f"\n=== 仅 pro 有（保留，不自动删除）: {len(only_pro)} 个 ===")
    for n in only_pro[:40]:
        print(f"  ! {n}")
    if len(only_pro) > 40:
        print(f"  ... 另有 {len(only_pro) - 40} 个")
    return 0


def sync() -> int:
    names = sync_files()
    bad_chars = [n for n in names if any(c in n for c in (" ", "\\", "\n", "\r"))]
    if bad_chars:
        print(f"错误：以下路径含空格/反斜杠，sha256sum -c 需额外转义，先处理：\n"
              f"  {bad_chars[:10]}", file=sys.stderr)
        return 2

    TARBALL.parent.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    with tarfile.open(TARBALL, "w:gz") as tf:
        for n in names:
            p = ROOT / n
            tf.add(p, arcname=n, recursive=False)
            manifest_lines.append(
                f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {n}\n")
        data = "".join(manifest_lines).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    print(f"打包 {len(names)} 个文件 -> {TARBALL.stat().st_size / 1024 / 1024:.1f} MB")

    r = sh(["scp", str(TARBALL), f"{REMOTE}:/tmp/repo_sync.tar.gz"])
    if r.returncode != 0:
        print(f"上传失败: {r.stderr.decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        return 1

    cmd = (f"cd {RROOT} && tar -xzf /tmp/repo_sync.tar.gz && "
           f"sha256sum -c {MANIFEST} > /tmp/repo_sync_check.txt 2>&1; "
           f"echo \"OK=$(grep -c ': OK$' /tmp/repo_sync_check.txt)\"; "
           f"echo \"FAIL=$(grep -v ': OK$' /tmp/repo_sync_check.txt | wc -l)\"; "
           f"grep -v ': OK$' /tmp/repo_sync_check.txt | head -10; "
           f"rm -f /tmp/repo_sync.tar.gz {MANIFEST}")
    r = sh(["ssh", REMOTE, cmd])
    out = r.stdout.decode("utf-8", "replace").strip()
    print(out)
    if r.returncode != 0:
        print(f"远端解压/校验异常: {r.stderr.decode('utf-8', 'replace')[:300]}",
              file=sys.stderr)
        return 1
    if f"OK={len(names)}" not in out or "FAIL=0" not in out:
        print("校验未通过，请检查上面的失败清单", file=sys.stderr)
        return 1
    print(f"PASS: {len(names)} 个文件与 win 逐字节一致")
    return 0


def pull_results() -> int:
    print("\n=== pro -> win 拉回运行成果 ===")
    for rel in RESULT_FILES:
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        r = sh(["scp", f"{REMOTE}:{RROOT}/{rel}", str(dst)])
        if r.returncode != 0:
            print(f"  FAIL {rel}: {r.stderr.decode('utf-8', 'replace')[:160]}")
            continue
        print(f"  OK   {rel}  {dst.stat().st_size / 1024 / 1024:.2f} MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只列差异，不传文件")
    ap.add_argument("--pull-results", action="store_true",
                    help="同步后把 pro 的最新运行成果拉回 win")
    args = ap.parse_args()
    if args.check:
        return check()
    rc = sync()
    if rc == 0 and args.pull_results:
        pull_results()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
