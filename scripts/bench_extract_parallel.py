"""extract() 并行模型诊断：证明 CPU 密集段必须用多进程（GIL），多线程无效。

对照组（都用本地缓存文件，排除网络干扰）：
  - serial            单进程串行
  - thread-N          ThreadPoolExecutor（GIL 限制，预期无加速）
  - process-N         ProcessPoolExecutor（绕开 GIL，预期随核数加速）

这是"rustfs-combo 该把多进程放在哪一层"的直接证据。

用法：
  python scripts/bench_extract_parallel.py --n 400
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("H1_FROZEN_EMIT", "0")

# 必须是顶层函数，Windows spawn 才能 pickle
def _work(path_str: str):
    from annual_semi_extraction.h1.extractor import extract
    from pathlib import Path
    rec = extract(Path(path_str))
    return 1 if rec and rec.get("headings") else 0


def _init_worker():
    # 每个子进程预热一次（加载 pattern_matcher / 规范表），避免把导入算进计时抖动
    os.environ.setdefault("H1_FROZEN_EMIT", "0")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--root", default="data/md_cache/published")
    args = ap.parse_args()

    files = [str(p) for p in sorted(Path(args.root).rglob("*.md"))[: args.n]]
    print(f"样本: {len(files)} 个本地缓存 MD 文件")
    if not files:
        return

    # 预热主进程
    _work(files[0])

    # 串行
    t0 = time.perf_counter()
    for f in files:
        _work(f)
    t_serial = time.perf_counter() - t0

    print(f"\n{'模式':<14}{'耗时(s)':>10}{'吞吐(f/s)':>12}{'加速比':>10}")
    print("-" * 46)
    print(f"{'serial':<14}{t_serial:>10.2f}{len(files)/t_serial:>12.1f}{1.0:>10.2f}x")

    for n in (4, 8, 16):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as ex:
            list(ex.map(_work, files))
        t = time.perf_counter() - t0
        print(f"{'thread-'+str(n):<14}{t:>10.2f}{len(files)/t:>12.1f}{t_serial/t:>10.2f}x")

    for n in (4, 8):
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=n, initializer=_init_worker) as ex:
            list(ex.map(_work, files, chunksize=16))
        t = time.perf_counter() - t0
        print(f"{'process-'+str(n):<14}{t:>10.2f}{len(files)/t:>12.1f}{t_serial/t:>10.2f}x")

    print("\n结论: 若 thread 组不随核数增长而 process 组增长，则 CPU 段必须用多进程。")


if __name__ == "__main__":
    main()
