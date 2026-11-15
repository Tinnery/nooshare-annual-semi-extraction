"""用「序号规则」校验「PG 标题库识别结果」，评估一级标题正确识别比例。

对全量 MD 逐份取两个独立判定：
  library_match   extract() 内部按当前 PG 标准库匹配（精确 hash / 模糊前缀）
  ordinal_valid   ordinal_verdict() 的 PASS（不跳号、不重复）

四象限交叉：
  A 库命中 & 序号 PASS  -> 可判为「正确识别」（核心指标）
  B 库命中 & 序号违规   -> 疑似误命中 / 抽取缺陷，需排查
  C 库未命中 & 序号 PASS -> 抽取合规但标准库未覆盖，下一轮入库候选
  D 库未命中 & 序号违规 -> 抽取失败或长尾，人工排查
  E 无 headings          -> 抽取失败

分母给两个口径：全部 MD、以及可抽取 MD（排除 E）。
另按命中策略（精确 / 模糊）拆分，检验模糊匹配是否更不可靠。
"""
from __future__ import annotations

import argparse
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
    from annual_semi_extraction.h1.pattern_matcher import (
        get_pattern_matcher, _normalize_pattern, _pattern_hash,
    )

    slot = Path(key).stem
    p = Path(tmp_root) / f"w{os.getpid()}" / Path(key).name
    try:
        p.write_bytes(get_client().read_bytes(key))
        rec = extract(p)
        p.unlink(missing_ok=True)
    except Exception as e:
        return {"slot": slot, "quad": "E", "reason": f"exception:{type(e).__name__}"}
    if rec is None or not rec.get("headings"):
        return {"slot": slot, "quad": "E", "reason": "no_headings"}

    lib = bool(rec.get("library_match"))
    ov = rec.get("ordinal_verdict")
    if ov is None:  # 部署旧版 extractor 时显式失败，不静默
        return {"slot": slot, "quad": "E", "reason": "missing_ordinal_verdict"}
    valid = ov == "PASS"

    strategy = ""
    if lib:
        m = get_pattern_matcher()
        raw = [h["raw_name"] for h in rec["headings"]]
        strategy = ("exact" if _pattern_hash(_normalize_pattern(raw)) in m._patterns
                    else "fuzzy")
    quad = "A" if (lib and valid) else "B" if lib else "C" if valid else "D"
    return {
        "slot": slot, "quad": quad, "lib": lib, "strategy": strategy,
        "ov": ov, "method": rec.get("extraction_method"),
        "n": rec.get("ordinal_n"), "missing": rec.get("ordinal_missing", []),
        "dupes": rec.get("ordinal_duplicates", []),
        "lib_count": rec.get("library_count"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=16)
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/library_coverage_eval.json")
    args = ap.parse_args()

    os.environ["RUSTFS_ENDPOINT"] = args.endpoint
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = args.endpoint
    _r._server_time_offset = None

    import annual_semi_extraction.h1.extractor as _ext
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    for flag in ("HAS_LIBRARY_MATCH", "HAS_TITLE_ANCHOR", "HAS_ORDINAL_VERDICT"):
        if not getattr(_ext, flag, False):
            print(f"错误：extractor.py 缺少 {flag}，请同步代码")
            return 2
    matcher = get_pattern_matcher()
    print(f"标准库: {matcher.size} 条 pattern, {matcher.title_count} 个标题词条")

    from annual_semi_extraction.rustfs import get_client
    keys = [o["key"] for o in get_client().list_objects(prefix="published/")
            if o["key"].endswith(".md")]
    if args.limit:
        keys = keys[: args.limit]
    print(f"待评估 MD: {len(keys)}")

    tmp_root = tempfile.mkdtemp(prefix="h1_eval_")
    quad = Counter()
    strategy = Counter()
    ov_counter = Counter()
    method_counter: dict[str, Counter] = defaultdict(Counter)
    lib_counts = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)
    unique_slots: dict[str, set[str]] = defaultdict(set)

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.parallel,
                             initializer=_init,
                             initargs=(args.endpoint, tmp_root)) as ex:
        for r in ex.map(_work, [(k, tmp_root) for k in keys], chunksize=16):
            q = r["quad"]
            quad[q] += 1
            unique_slots[q].add(r["slot"])
            if q == "E":
                ov_counter["no_headings:" + r.get("reason", "?")] += 1
                continue
            ov_counter[r["ov"]] += 1
            method_counter[r["method"]][q] += 1
            if r["lib"]:
                strategy[r["strategy"]] += 1
                strategy[r["strategy"] + ":" + ("PASS" if q == "A" else "FAIL")] += 1
                if r.get("lib_count"):
                    lib_counts[r["lib_count"]] += 1
            if len(samples[q]) < 6:
                samples[q].append(r)
    import shutil
    shutil.rmtree(tmp_root, ignore_errors=True)
    elapsed = time.perf_counter() - t0

    total = len(keys)
    evaluable = total - quad["E"]
    A, B, C, D = quad["A"], quad["B"], quad["C"], quad["D"]
    lib_total = A + B
    print(f"\n耗时 {elapsed:.1f}s ({total/elapsed:.1f} files/s)")
    print("\n=== 四象限 ===")
    print(f"  A 库命中 & 序号PASS  : {A:>7}  {A/total*100:>6.2f}% 全量  <- 正确识别")
    print(f"  B 库命中 & 序号违规  : {B:>7}  {B/total*100:>6.2f}% 全量  <- 误命中/抽取缺陷")
    print(f"  C 未命中 & 序号PASS  : {C:>7}  {C/total*100:>6.2f}% 全量  <- 入库候选")
    print(f"  D 未命中 & 序号违规  : {D:>7}  {D/total*100:>6.2f}% 全量")
    print(f"  E 无 headings        : {quad['E']:>7}  {quad['E']/total*100:>6.2f}% 全量")
    print(f"\n=== 核心指标 ===")
    print(f"  标题库覆盖率 (A+B)/全量          : {lib_total}/{total} = {lib_total/total*100:.2f}%")
    print(f"  标题库覆盖率 (A+B)/可抽取        : {lib_total}/{evaluable} = {lib_total/evaluable*100:.2f}%")
    print(f"  正确识别率   A/全量               : {A}/{total} = {A/total*100:.2f}%")
    print(f"  正确识别率   A/可抽取             : {A}/{evaluable} = {A/evaluable*100:.2f}%")
    print(f"  库命中里的序号合规率 A/(A+B)      : {A}/{lib_total} = {A/lib_total*100:.2f}%")
    print(f"  唯一 slot 口径 A/全部唯一slot     : {len(unique_slots['A'])}/"
          f"{len(set().union(*unique_slots.values()))} = "
          f"{len(unique_slots['A'])/len(set().union(*unique_slots.values()))*100:.2f}%")

    print("\n=== 命中策略拆分 ===")
    for s in ("exact", "fuzzy"):
        n = strategy[s]
        if n:
            good = strategy[s + ":PASS"]
            print(f"  {s:<6} 命中 {n:>7}  其中序号PASS {good:>7} ({good/n*100:.2f}%)")

    print("\n=== 序号规则判定分布（可抽取部分）===")
    for k, v in ov_counter.most_common():
        print(f"  {k:<28}{v:>8}")

    print("\n=== 按 extraction_method ===")
    for m, c in sorted(method_counter.items(), key=lambda x: -sum(x[1].values())):
        print(f"  {m:<14} A={c['A']:<7} B={c['B']:<6} C={c['C']:<7} D={c['D']:<6}")

    print("\n=== 各象限样本 ===")
    for q in ("A", "B", "C", "D"):
        for r in samples[q][:3]:
            print(f"  [{q}] {r['slot']} ov={r.get('ov')} "
                  f"strategy={r.get('strategy')!r} missing={r.get('missing')} "
                  f"lib_count={r.get('lib_count')}")

    out = {
        "total_md": total, "evaluable": evaluable,
        "quad": dict(quad), "strategy": dict(strategy),
        "unique_slots_A": len(unique_slots["A"]),
        "unique_slots_all": len(set().union(*unique_slots.values())),
        "library_patterns": matcher.size,
        "correct_rate_all": A / total,
        "correct_rate_evaluable": A / evaluable,
        "library_coverage_all": lib_total / total,
        "sequence_pass_within_library": A / lib_total if lib_total else 0,
        "elapsed_s": round(elapsed, 1),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
