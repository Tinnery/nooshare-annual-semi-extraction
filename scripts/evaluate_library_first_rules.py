"""全量量化「库词表前置准入」的修复效果与误伤。

对每份 MD 复现候选构造，比较：
  S0 现状 _detect_l1(所有候选)
  S2 前置准入：只留 name 在库词表/法规集 或 legal_name_of 非空的候选
统计：
  - 结果序列发生变化的文档数
  - 变化后是否能命中 PG 标准库（library_match 从 False -> True）
  - 变化后序号规则是否仍 PASS（不能变坏）
  - ch_zh 对照组的变化率（衡量误伤面）
输出明细到 data/library_first_diff.jsonl
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("H1_FROZEN_EMIT", "0")


def _init(endpoint: str, tmp_root: str) -> None:
    os.environ["RUSTFS_ENDPOINT"] = endpoint
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = endpoint
    _r._server_time_offset = None
    from annual_semi_extraction.rustfs import get_client
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    get_client()
    get_pattern_matcher()._load()
    d = Path(tmp_root) / f"w{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)


def _work(arg: tuple[str, str]):
    key, tmp_root = arg
    import os as _os
    from pathlib import Path as P
    from annual_semi_extraction.rustfs import get_client
    from annual_semi_extraction.h1 import extractor as E
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    from annual_semi_extraction.h1.morphology import LEGAL_NAMES

    slot = P(key).stem
    p = P(tmp_root) / f"w{_os.getpid()}" / P(key).name
    try:
        raw = get_client().read_bytes(key)
    except Exception as e:
        return {"slot": slot, "error": type(e).__name__}
    try:
        _, year_s, period_s = slot.split("_")
        year, period = int(year_s), int(period_s)
    except Exception:
        return {"slot": slot, "error": "bad_slot"}

    m = get_pattern_matcher()
    vocab = set(m._title_set) | set(LEGAL_NAMES)
    lib = m._patterns

    items, offset = [], 0
    for lineno, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        start, end = offset, offset + len(raw_line)
        offset = end
        line = raw_line.decode("utf-8", errors="replace")
        body = line.rstrip("\r\n")
        hm = E.RE_H.match(body)
        md_level = len(hm.group(1)) if hm else 0
        raw_title = hm.group(2).strip() if hm else body.strip()
        eff = E.TITLE_PREFIX.sub("", raw_title, count=1)
        if not eff or eff[:1] not in "第一二三四五六七八九十0123456789（(":
            continue
        info = E.parse_numbered_line(eff)
        if info is None:
            continue
        info.update({"line": lineno, "start": start, "end": end,
                     "verbatim": line, "md_level": md_level,
                     "heading_like": E._heading_like(info["name"])})
        items.append(info)

    expected = E.expected_sections(year, period)
    cond = E._conditional_ords(year, period)

    def solve(pool):
        for system in ("CH_ZH", "CN_DUN"):
            sub = [it for it in pool if it["system"] == system]
            r = E._detect_l1(sub, expected, cond)
            if r:
                return system, r
        return None, None

    def verdict(seq):
        # 用 ordinal 判定
        ords = sorted({it["ordinal"] for it in seq if it["ordinal"] > 0})
        if not ords:
            return "NO_NUMBERED"
        missing = set(range(1, max(ords) + 1)) - set(ords)
        return "PASS" if not missing else "GAP"

    def lib_hit(names):
        # 必须与 matcher 的策略1 完全一致：normalize 后 hash
        from annual_semi_extraction.h1.pattern_matcher import (
            _normalize_pattern, _pattern_hash,
        )
        return _pattern_hash(_normalize_pattern(list(names))) in lib

    s0_sys, s0 = solve(items)
    if s0 is None:
        return {"slot": slot, "error": "no_l1"}

    filtered = [it for it in items
                if it["name"] in vocab or E.legal_name_of(it["name"])]
    s2_sys, s2 = solve(filtered)
    if s2 is None:
        return {"slot": slot, "method": s0_sys, "changed": False,
                "s2_failed": True, "s0": [it["name"] for it in s0],
                "s0_lines": [it["line"] for it in s0]}

    a = [it["name"] for it in s0]
    b = [it["name"] for it in s2]
    return {
        "slot": slot, "method": s0_sys, "s2_method": s2_sys,
        "changed": a != b,
        "s0": a, "s2": b,
        "s0_lines": [it["line"] for it in s0],
        "s2_lines": [it["line"] for it in s2],
        "s0_ov": verdict(s0), "s2_ov": verdict(s2),
        "s0_lib": lib_hit(a), "s2_lib": lib_hit(b),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/library_first_diff.jsonl")
    args = ap.parse_args()

    os.environ["RUSTFS_ENDPOINT"] = args.endpoint
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = args.endpoint
    _r._server_time_offset = None
    from annual_semi_extraction.rustfs import get_client
    keys = [o["key"] for o in get_client().list_objects(prefix="published/")
            if o["key"].endswith(".md")]
    if args.limit:
        keys = keys[: args.limit]
    print(f"待评估 MD: {len(keys)}")

    tmp_root = tempfile.mkdtemp(prefix="libfirst_")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fout = out.open("w", encoding="utf-8")
    stat = Counter()
    by_method: dict[str, Counter] = {}
    samples = []
    t0 = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=args.parallel, initializer=_init,
                                 initargs=(args.endpoint, tmp_root)) as ex:
            for r in ex.map(_work, [(k, tmp_root) for k in keys], chunksize=16):
                if "error" in r:
                    stat["error:" + r["error"]] += 1
                    continue
                stat["evaluable"] += 1
                m = r["method"]
                c = by_method.setdefault(m, Counter())
                c["total"] += 1
                if r.get("s2_failed"):
                    stat["s2_failed"] += 1
                    c["s2_failed"] += 1
                if r["changed"]:
                    stat["changed"] += 1
                    c["changed"] += 1
                    fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                    if len(samples) < 8:
                        samples.append(r)
                    if r["s0_lib"] is False and r["s2_lib"] is True:
                        stat["lib_false_to_true"] += 1
                    if r["s0_ov"] == "PASS" and r["s2_ov"] != "PASS":
                        stat["ordinal_degraded"] += 1
                    if r["s0_ov"] != "PASS" and r["s2_ov"] == "PASS":
                        stat["ordinal_fixed"] += 1
                else:
                    c["same"] += 1
    finally:
        fout.close()
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)
    elapsed = time.perf_counter() - t0
    print(f"耗时 {elapsed:.1f}s ({len(keys)/elapsed:.1f} files/s)")
    print(f"\n=== 汇总 ===")
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"\n=== 按原 method ===")
    for m, c in sorted(by_method.items(), key=lambda x: -x[1]["total"]):
        n = c["total"]
        print(f"  {m:<10} n={n:<7} 改变={c['changed']} ({c['changed']/n*100:.2f}%) "
              f"S2失败={c['s2_failed']}")
    print("\n=== 变化样例 ===")
    for s in samples:
        print(f"  {s['slot']} {s['method']} s0_lib={s['s0_lib']} s2_lib={s['s2_lib']} "
              f"ov {s['s0_ov']}->{s['s2_ov']}")
        print(f"    S0: {s['s0'][:4]}")
        print(f"    S2: {s['s2'][:4]}")
        print(f"    lines S0={s['s0_lines'][:6]} S2={s['s2_lines'][:6]}")
    print(f"\n-> 明细 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
