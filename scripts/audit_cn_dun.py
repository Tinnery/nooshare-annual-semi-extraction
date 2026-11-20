"""全量审计 cn_dun & ordinal_valid=PASS 的文档，并留 headings 明细供后续抽查。

输出：
  data/cn_dun_audit.jsonl   逐文档（cn_dun & ordinal PASS）明细，含 headings 的
                            ordinal / raw_name / md_level / line / marker
  data/cn_dun_audit.json    汇总统计
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter, defaultdict
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
    get_pattern_matcher()
    d = Path(tmp_root) / f"w{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)


def _work(arg: tuple[str, str]):
    key, tmp_root = arg
    from pathlib import Path
    from annual_semi_extraction.rustfs import get_client
    from annual_semi_extraction.h1.extractor import extract

    slot = Path(key).stem
    p = Path(tmp_root) / f"w{os.getpid()}" / Path(key).name
    try:
        p.write_bytes(get_client().read_bytes(key))
        rec = extract(p)
        p.unlink(missing_ok=True)
    except Exception as e:
        return {"slot": slot, "error": f"{type(e).__name__}"}
    if rec is None or not rec.get("headings"):
        return {"slot": slot, "error": "no_headings"}

    method = rec.get("extraction_method")
    ov = rec.get("ordinal_verdict")
    lib = bool(rec.get("library_match"))
    pattern = [h["raw_name"] for h in rec["headings"] if h.get("raw_name")]
    quad = ("A" if lib and ov == "PASS" else "B" if lib
            else "C" if ov == "PASS" else "D")
    base = {
        "slot": slot, "method": method, "ordinal_verdict": ov,
        "quad": quad, "library_match": lib,
        "library_count": rec.get("library_count"),
        "pattern": pattern,
        "ordinal_missing": rec.get("ordinal_missing", []),
    }
    # 仅 cn_dun & PASS 需要完整 headings 明细，控制 IPC
    if method == "cn_dun" and ov == "PASS":
        base["headings"] = [
            {"ordinal": h.get("ordinal"), "raw_name": h.get("raw_name"),
             "md_level": h.get("md_level"), "line": h.get("line"),
             "marker": h.get("marker"), "numbering_system": h.get("numbering_system")}
            for h in rec["headings"]
        ]
        base["pattern_in_lib"] = lib
    return base


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/cn_dun_audit.json")
    ap.add_argument("--details", default="data/cn_dun_audit.jsonl")
    args = ap.parse_args()

    os.environ["RUSTFS_ENDPOINT"] = args.endpoint
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = args.endpoint
    _r._server_time_offset = None

    from annual_semi_extraction.rustfs import get_client
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    matcher = get_pattern_matcher()
    matcher._load()  # 主进程需显式加载，否则 _patterns 为空
    lib_patterns = {tuple(d["pattern"]) for d in matcher._patterns.values()}
    print(f"PG 标准库: {matcher.size} 条 pattern, {matcher.title_count} 个标题词条")

    keys = [o["key"] for o in get_client().list_objects(prefix="published/")
            if o["key"].endswith(".md")]
    if args.limit:
        keys = keys[: args.limit]
    print(f"待审计 MD: {len(keys)}")

    tmp_root = tempfile.mkdtemp(prefix="cn_dun_audit_")
    details = Path(args.details)
    details.parent.mkdir(parents=True, exist_ok=True)
    fout = details.open("w", encoding="utf-8")

    method_counter = Counter()
    quad_counter = Counter()
    cn_pass_quad = Counter()
    cn_pass_total = 0
    cn_pass_in_lib_docs = 0
    cn_pass_patterns: Counter = Counter()
    lib_hit_by_pattern: Counter = Counter()
    lib_cn_hit_by_pattern: Counter = Counter()
    total = 0
    errors = 0

    t0 = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=args.parallel, initializer=_init,
                                 initargs=(args.endpoint, tmp_root)) as ex:
            for r in ex.map(_work, [(k, tmp_root) for k in keys], chunksize=16):
                total += 1
                if "error" in r:
                    errors += 1
                    continue
                method_counter[r["method"]] += 1
                quad_counter[r["quad"]] += 1
                pat = tuple(r["pattern"])
                if r["library_match"]:
                    lib_hit_by_pattern[pat] += 1
                if r["method"] == "cn_dun" and r["ordinal_verdict"] == "PASS":
                    cn_pass_total += 1
                    cn_pass_quad[r["quad"]] += 1
                    cn_pass_patterns[pat] += 1
                    if r["library_match"]:
                        cn_pass_in_lib_docs += 1
                        lib_cn_hit_by_pattern[pat] += 1
                    fout.write(json.dumps(r, ensure_ascii=False) + "\n")
    finally:
        fout.close()
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)
    elapsed = time.perf_counter() - t0

    print(f"\n耗时 {elapsed:.1f}s ({total/elapsed:.1f} files/s)")
    print("\n=== 第一步：全量统计 ===")
    print(f"  总 MD {total} | 无 headings/异常 {errors} | 有效 {total-errors}")
    print(f"  extraction_method 分布: {dict(method_counter)}")
    print(f"  四象限(35 条库口径): {dict(quad_counter)}")
    C = quad_counter["C"]
    print(f"\n  cn_dun & ordinal PASS 的文档数: {cn_pass_total}")
    print(f"    占全部 MD        : {cn_pass_total/total*100:.2f}%")
    print(f"    占有效 MD        : {cn_pass_total/(total-errors)*100:.2f}%")
    print(f"    四象限分布       : {dict(cn_pass_quad)}")
    print(f"    其中 C 类        : {cn_pass_quad['C']} / C 类总数 {C} "
          f"= {cn_pass_quad['C']/C*100:.2f}%")
    print(f"    命中标准库(A+B)  : {cn_pass_in_lib_docs} "
          f"({cn_pass_in_lib_docs/cn_pass_total*100:.2f}% of cn_dun PASS)")

    # 35 条标准库里，哪些 pattern 有 cn_dun 文档贡献
    lib_pats_with_cn = [p for p in lib_patterns if lib_cn_hit_by_pattern.get(p, 0) > 0]
    pct_lib = (len(lib_pats_with_cn) / len(lib_patterns) * 100
               if lib_patterns else 0.0)
    print(f"\n  35 条标准库中，pattern 被 cn_dun&PASS 文档命中过的: "
          f"{len(lib_pats_with_cn)}/{len(lib_patterns)} ({pct_lib:.1f}%)")
    print("  这些 pattern 的 cn_dun 命中数 / 总命中数:")
    for p in sorted(lib_pats_with_cn,
                    key=lambda p: -lib_cn_hit_by_pattern[p])[:10]:
        print(f"    cn={lib_cn_hit_by_pattern[p]:<6} all={lib_hit_by_pattern[p]:<7} "
              f"p0={p[0][:28]!r}")

    print(f"\n  cn_dun&PASS 文档涉及的不同 pattern: {len(cn_pass_patterns)}")
    print(f"  -> 明细 {details}")

    out = {
        "total_md": total, "errors": errors, "evaluable": total - errors,
        "method": dict(method_counter), "quad": dict(quad_counter),
        "cn_dun_pass": cn_pass_total,
        "cn_dun_pass_quad": dict(cn_pass_quad),
        "C_total": C,
        "cn_dun_pass_in_C_rate": cn_pass_quad["C"] / C if C else 0,
        "cn_dun_pass_in_lib_docs": cn_pass_in_lib_docs,
        "lib_patterns_with_cn_dun": len(lib_pats_with_cn),
        "lib_patterns_total": len(lib_patterns),
        "cn_dun_pass_distinct_patterns": len(cn_pass_patterns),
        "elapsed_s": round(elapsed, 1),
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> 汇总 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
