"""验证「库词表作为 _rep_rank 打分信号」（不剔除任何候选）的效果。

S0  现状 _rep_rank = (md_level==1, heading_like, len(name))
S4a rank = (in_vocab, md_level==1, heading_like, len(name))
S4b rank = (md_level==1, in_vocab, heading_like, len(name))

关键：候选集完全不变，只改变同序号内「选谁当代表」的优先级。
因此不会产生序号空洞 —— 这是与「前置准入」的本质区别。
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
    from annual_semi_extraction.h1.pattern_matcher import (
        get_pattern_matcher, _normalize_pattern, _pattern_hash,
    )
    from annual_semi_extraction.h1.morphology import LEGAL_NAMES

    slot = P(key).stem
    try:
        raw = get_client().read_bytes(key)
        year, period = int(slot.split("_")[1]), int(slot.split("_")[2])
    except Exception as e:
        return {"slot": slot, "error": type(e).__name__}

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

    def in_vocab(it):
        return 1 if (it["name"] in vocab or E.legal_name_of(it["name"])) else 0

    def rank0(it):
        return (1 if it["md_level"] == 1 else 0,
                1 if it["heading_like"] else 0, len(it["name"]))

    def rank_a(it):
        return (in_vocab(it),) + rank0(it)

    def rank_b(it):
        return (1 if it["md_level"] == 1 else 0, in_vocab(it),
                1 if it["heading_like"] else 0, len(it["name"]))

    def solve(pool, rankfn):
        for system in ("CH_ZH", "CN_DUN"):
            sub = [it for it in pool if it["system"] == system]
            best = {}
            for it in sub:
                o = it["ordinal"]
                if o < 1 or o > E.ORD_CAP:
                    continue
                if o not in best or rankfn(it) > rankfn(best[o]):
                    best[o] = it
            ords = sorted(best)
            if len(ords) < 4:
                continue
            rate = sum(1 for o in ords if E.legal_name_of(best[o]["name"])) / len(ords)
            if rate < 0.3:
                continue
            if not all(best[o]["md_level"] == 1 or best[o]["heading_like"]
                       for o in ords):
                continue
            return system, [best[o] for o in ords]
        return None, None

    def verdict(seq):
        ords = sorted({it["ordinal"] for it in seq if it["ordinal"] > 0})
        if not ords:
            return "NO_NUMBERED"
        return "PASS" if not (set(range(1, max(ords) + 1)) - set(ords)) else "GAP"

    def lib_hit(names):
        return _pattern_hash(_normalize_pattern(list(names))) in lib

    _, s0 = solve(items, rank0)
    if s0 is None:
        return {"slot": slot, "error": "no_l1"}
    _, sa = solve(items, rank_a)
    _, sb = solve(items, rank_b)
    if sa is None or sb is None:
        return {"slot": slot, "error": "variant_failed"}

    a = [it["name"] for it in s0]
    return {
        "slot": slot, "method": s0[0]["system"] if s0 else "?",
        "s0": a, "s4a": [it["name"] for it in sa],
        "s4b": [it["name"] for it in sb],
        "s0_lines": [it["line"] for it in s0],
        "s4a_lines": [it["line"] for it in sa],
        "s0_ov": verdict(s0), "s4a_ov": verdict(sa), "s4b_ov": verdict(sb),
        "s0_lib": lib_hit(a), "s4a_lib": lib_hit([it["name"] for it in sa]),
        "s4b_lib": lib_hit([it["name"] for it in sb]),
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/library_rank_diff.jsonl")
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

    tmp_root = tempfile.mkdtemp(prefix="librank_")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fout = out.open("w", encoding="utf-8")
    stat = Counter()
    user_sample = None
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
                a, x, y = r["s0"], r["s4a"], r["s4b"]
                for tag, z, ov in (("a", x, r["s4a_ov"]), ("b", y, r["s4b_ov"])):
                    if z != a:
                        stat[f"changed_{tag}"] += 1
                        if r["s0_ov"] == "PASS" and ov != "PASS":
                            stat[f"degraded_{tag}"] += 1
                        if r["s0_ov"] != "PASS" and ov == "PASS":
                            stat[f"fixed_{tag}"] += 1
                        if not r["s0_lib"] and r[f"s4{tag}_lib"]:
                            stat[f"lib_gain_{tag}"] += 1
                if r["slot"] == "600010_2008_2":
                    user_sample = r
                if x != a and len(samples) < 6:
                    samples.append(r)
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    finally:
        fout.close()
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)
    elapsed = time.perf_counter() - t0
    print(f"耗时 {elapsed:.1f}s ({len(keys)/elapsed:.1f} files/s)")
    print("\n=== 汇总（候选集不变，仅改同序号代表优先级）===")
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")

    print("\n=== 用户样本 600010_2008_2 ===")
    if user_sample:
        u = user_sample
        print(f"  S0 : {u['s0'][:4]} lines={u['s0_lines'][:6]}")
        print(f"  S4a: {u['s4a'][:4]} lines={u['s4a_lines'][:6]}")
        print(f"  S4b: {u['s4b'][:4]}")
        print(f"  ov S0={u['s0_ov']} S4a={u['s4a_ov']} S4b={u['s4b_ov']}")
    else:
        print("  未找到")

    print("\n=== 改变样例（S4a）===")
    for s in samples:
        print(f"  {s['slot']} ov {s['s0_ov']}->{s['s4a_ov']} "
              f"lib {s['s0_lib']}->{s['s4a_lib']}")
        print(f"    S0 : {s['s0'][:4]}")
        print(f"    S4a: {s['s4a'][:4]}")
    print(f"\n-> 明细 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
