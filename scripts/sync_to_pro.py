"""把运行必需的 Python 模块同步到 pro 主机，并逐文件校验 sha256。

背景：pro 主机目录不是 git 仓库，历史上曾因只 scp 了 cli.py /
pattern_matcher.py 而漏掉 extractor.py，导致跑的是旧版抽取逻辑、
library_match 字段缺失，结果静默错误。

用法：
    python scripts/sync_to_pro.py            # 同步 + 校验
    python scripts/sync_to_pro.py --check    # 只校验，不传文件
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "travis@192.168.31.233"
REMOTE_ROOT = "/home/travis/repos/nooshare-annual-semi-extraction"

# 运行 rustfs-combo 真正会 import 的模块。改动其中任一都必须同步。
FILES = [
    "annual_semi_extraction/cli.py",
    "annual_semi_extraction/rustfs.py",
    "annual_semi_extraction/config.py",
    "annual_semi_extraction/h1/__init__.py",
    "annual_semi_extraction/h1/corpus.py",
    "annual_semi_extraction/h1/extractor.py",
    "annual_semi_extraction/h1/frozen_judge.py",
    "annual_semi_extraction/h1/morphology.py",
    "annual_semi_extraction/h1/normalizer.py",
    "annual_semi_extraction/h1/numbering.py",
    "annual_semi_extraction/h1/pattern_matcher.py",
]


def local_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote_sha(rel: str) -> str | None:
    cmd = ["ssh", REMOTE, f"sha256sum {REMOTE_ROOT}/{rel} 2>/dev/null"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    return out.split()[0] if out else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不传文件")
    args = ap.parse_args()

    bad = []
    for rel in FILES:
        local = ROOT / rel
        if not local.exists():
            print(f"MISSING  {rel} (本地不存在)")
            bad.append(rel)
            continue
        want = local_sha(local)
        got = remote_sha(rel)
        if got != want and not args.check:
            dst = f"{REMOTE}:{REMOTE_ROOT}/{rel}"
            r = subprocess.run(["scp", str(local), dst], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"SCP-FAIL {rel}: {r.stderr.strip()}")
                bad.append(rel)
                continue
            got = remote_sha(rel)
        ok = got == want
        print(f"{'OK      ' if ok else 'MISMATCH'}  {rel}"
              + ("" if ok else f"  {want[:8]} != {(got or 'none')[:8]}"))
        if not ok:
            bad.append(rel)

    print()
    if bad:
        print(f"FAILED: {len(bad)} 个文件不一致 -> {bad}")
        return 1
    print(f"PASS: {len(FILES)} 个文件全部一致 (check_only={args.check})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
