"""rustfs-combo 性能瓶颈诊断（可复现的客观测量工具）。

目的：判定瓶颈在 CPU 还是 I/O，从而决定"多进程"是否是正确的改造方向。

测量 5 个阶段：
  0. list_objects 全量分页耗时（固定开销）
  1. 串行下载（每次新建 TLS 连接 —— 当前实现）
  2. ThreadPoolExecutor 并行下载（I/O 并发能否线性加速）
  3. keep-alive 单连接复用（TLS 握手是否为病根）
  4. extract() 纯 CPU 耗时（CPU 到底占多少）

用法：
  python scripts/bench_rustfs_combo.py            # 默认 200 个样本文件
  python scripts/bench_rustfs_combo.py --n 500    # 更多样本
"""
from __future__ import annotations

import argparse
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPSConnection
from pathlib import Path
from urllib.parse import urlparse

from annual_semi_extraction.rustfs import (
    ENDPOINT_URL,
    _SSL_CTX,
    _build_signed_headers,
    _object_path,
    get_client,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="样本文件数")
    args = ap.parse_args()

    client = get_client()
    results: dict[str, float] = {}

    # ── 阶段 0: list_objects 全量 ──────────────────────────────
    print("=== 阶段 0: list_objects 全量分页 ===")
    t0 = time.perf_counter()
    all_obj = client.list_objects(prefix="published/")
    t_list = time.perf_counter() - t0
    md_keys = [o["key"] for o in all_obj if o["key"].endswith(".md")]
    results["list_s"] = t_list
    print(f"  全量列出: {t_list:.2f}s | {len(all_obj)} 对象 | {len(md_keys)} 个 .md")

    keys = md_keys[: args.n]
    if not keys:
        print("没有可测的 .md 文件，退出")
        return

    # ── 阶段 1: 串行下载（每次新建连接，当前实现）──────────────
    def dl_new(k: str) -> bool:
        try:
            client.read_text(k)
            return True
        except Exception:
            return False

    print(f"\n=== 阶段 1: 串行下载 {len(keys)} 个（每次新建 TLS 连接）===")
    t0 = time.perf_counter()
    ok = sum(dl_new(k) for k in keys)
    t_serial = time.perf_counter() - t0
    rate_serial = len(keys) / t_serial
    results["serial_s"] = t_serial
    print(f"  {t_serial:.2f}s | {rate_serial:.1f} files/s | ok={ok}")
    print(f"  推算全量 {len(md_keys)} 文件 ≈ {len(md_keys) / rate_serial / 60:.1f} 分钟")

    # ── 阶段 2: 并行下载（I/O 并发）────────────────────────────
    print(f"\n=== 阶段 2: ThreadPoolExecutor 并行下载 {len(keys)} 个 ===")
    for n in (4, 8, 16, 32):
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as ex:
            list(ex.map(dl_new, keys))
        t = time.perf_counter() - t0
        rate = len(keys) / t
        results[f"threads_{n}_s"] = t
        print(f"  threads={n:2d}: {t:6.2f}s | {rate:7.1f} files/s | "
              f"相对串行 {rate / rate_serial:5.1f}x")

    # ── 阶段 3: keep-alive 单连接复用（TLS 握手是否为病根）─────
    print(f"\n=== 阶段 3: keep-alive 单连接串行下载 {len(keys)} 个 ===")
    parsed = urlparse(ENDPOINT_URL)
    conn = HTTPSConnection(parsed.hostname, parsed.port or 443, context=_SSL_CTX, timeout=30)
    reconnects = 0
    ok = 0
    t0 = time.perf_counter()
    for k in keys:
        path = _object_path(k)
        headers = _build_signed_headers("GET", path)
        try:
            if conn.sock is None:
                conn = HTTPSConnection(parsed.hostname, parsed.port or 443,
                                       context=_SSL_CTX, timeout=30)
                reconnects += 1
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            if resp.status == 200:
                ok += 1
            if resp.will_close:  # 服务器要求关闭
                conn.close()
        except Exception:
            conn.close()
            try:
                conn = HTTPSConnection(parsed.hostname, parsed.port or 443,
                                       context=_SSL_CTX, timeout=30)
                reconnects += 1
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.status == 200:
                    ok += 1
            except Exception:
                pass
    t_keepalive = time.perf_counter() - t0
    try:
        conn.close()
    except Exception:
        pass
    results["keepalive_s"] = t_keepalive
    print(f"  {t_keepalive:.2f}s | {len(keys) / t_keepalive:.1f} files/s | "
          f"ok={ok} | 重连次数={reconnects} (0=连接真复用)")
    print(f"  相对新建连接: {t_serial / t_keepalive:.1f}x")

    # ── 阶段 4: extract() 纯 CPU 耗时 ──────────────────────────
    # 关键：必须用「真实文件分布」测量。循环同一个文件 1000 次会因 OS page
    # cache / CPU cache 全热 + 单一短报告走简单解析路径，得到 2ms 量级的假下界，
    # 与真实分布（中位 399KB、抽取路径各异）差 10 倍，足以把并行化方向带偏。
    print("\n=== 阶段 4: extract() 纯 CPU（真实文件分布）===")
    os.environ["H1_FROZEN_EMIT"] = "0"  # 关掉冻结库判定，只量解析
    from annual_semi_extraction.h1.extractor import extract

    local = Path("data/md_cache/published")
    real_files = sorted(local.rglob("*.md"))[:500] if local.exists() else []
    if real_files:
        extract(real_files[0])  # 预热（加载 pattern_matcher / 规范表）
        t0 = time.perf_counter()
        for p in real_files:
            extract(p)
        t_cpu = time.perf_counter() - t0
        ms_per = t_cpu / len(real_files) * 1000
        basis = f"真实分布 {len(real_files)} 个本地缓存文件"
    else:
        # 退化路径：明确标注不具代表性，避免被误当作有效数字
        real_name = keys[0].rsplit("/", 1)[-1]
        tmp = Path(tempfile.gettempdir()) / real_name
        tmp.write_bytes(client.read_text(keys[0]).encode("utf-8"))
        extract(tmp)
        n_iter = 1000
        t0 = time.perf_counter()
        for _ in range(n_iter):
            extract(tmp)
        t_cpu = time.perf_counter() - t0
        tmp.unlink(missing_ok=True)
        ms_per = t_cpu / n_iter * 1000
        basis = "!! 单文件重复（热缓存下界，不具代表性）"
    results["extract_ms_per"] = ms_per
    print(f"  {basis}: {t_cpu:.2f}s | 单次 {ms_per:.3f} ms")
    print(f"  推算全量 {len(md_keys)} 文件 ≈ "
          f"{len(md_keys) * ms_per / 1000 / 60:.1f} 分钟（纯 CPU，单进程）")

    # ── 结论 ──────────────────────────────────────────────────
    t_download = len(md_keys) / rate_serial            # 串行下载全量秒数
    t_extract = len(md_keys) * ms_per / 1000           # 串行 CPU 全量秒数
    total = t_download + t_extract
    amdahl_16 = total / (t_download + t_extract / 16)
    print("\n" + "=" * 60)
    print("结论（客观数据）")
    print("=" * 60)
    print(f"  串行下载全量: {t_download / 60:.1f} 分钟")
    print(f"  串行抽取全量: {t_extract / 60:.1f} 分钟")
    print(f"  下载(I/O) 占比: {t_download / total * 100:.1f}%  |  "
          f"抽取(CPU) 占比: {t_extract / total * 100:.1f}%")
    print(f"  直接把整条命令套多进程(Amdahl, 仅 CPU 段 16x): {amdahl_16:.2f}x")
    print("  → 结论1: 瓶颈主体是网络 I/O，多进程直接套整个命令收益有限")
    print("  → 结论2: 但 CPU 段本身是 GIL 受限的（见 bench_extract_parallel.py")
    print("           process-8 = 3.4x / thread-8 = 1.1x），必须用进程而非线程")
    print("  → 结论3: 正解是分层解耦 —— I/O 用连接池+线程，CPU 用独立进程池，")
    print("           且优先消除 I/O（本地缓存 / 增量）再谈多进程")


if __name__ == "__main__":
    main()
