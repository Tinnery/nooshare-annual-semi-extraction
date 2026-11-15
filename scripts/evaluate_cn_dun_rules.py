"""第三步：量化候选判据的拦截效果与误伤（ch_zh 作对照）。

候选规则：
  R1 首标题必须是「标准库 35 条 pattern 的首标题」或法规/锚定词表里的合法词
  R2 按 ordinal 顺序，heading 的 line 必须单调不减（禁止回跳）
  R3 R1 OR R2（任一命中即拦截）
  R4 R1 AND R2（同时命中才拦截，更保守）
  R5 首标题必须在标准库 35 条的首标题集合内（R1 的严格版）

误伤评估：同一规则施加到 ch_zh 文档上被拦的比例。
ch_zh 明细不在这份 jsonl 里，故用全量重新抽 ch_zh 样本对照。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("H1_FROZEN_EMIT", "0")

from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher  # noqa: E402
from annual_semi_extraction.h1.morphology import LEGAL_NAMES  # noqa: E402


def _init(endpoint: str, tmp_root: str) -> None:
    os.environ["RUSTFS_ENDPOINT"] = endpoint
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = endpoint
    _r._server_time_offset = None
    from annual_semi_extraction.rustfs import get_client
    get_client()
    d = Path(tmp_root) / f"w{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)


def _work(arg: tuple[str, str]):
    key, tmp_root = arg
    from pathlib import Path
    from annual_semi_extraction.rustfs import get_client
    from annual_semi_extraction.h1.extractor import extract
    p = Path(tmp_root) / f"w{os.getpid()}" / Path(key).name
    try:
        p.write_bytes(get_client().read_bytes(key))
        rec = extract(p)
        p.unlink(missing_ok=True)
    except Exception:
        return None
    if rec is None or not rec.get("headings"):
        return None
    hs = rec["headings"]
    return {
        "slot": Path(key).stem,
        "method": rec.get("extraction_method"),
        "first": hs[0].get("raw_name", ""),
        "lines": [h.get("line") or 0 for h in hs],
        "ov": rec.get("ordinal_verdict"),
    }


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/cn_dun_audit.jsonl")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    m = get_pattern_matcher()
    m._load()
    first_titles = {d["pattern"][0] for d in m._patterns.values()}
    legal = set(m._title_set) | set(LEGAL_NAMES)

    def r1(first: str) -> bool:
        return first in first_titles or first in legal

    def r2(lines: list[int]) -> bool:
        return any(lines[i] > lines[i + 1] for i in range(len(lines) - 1))

    def r5(first: str) -> bool:
        return first in first_titles

    # cn_dun 明细（全量已落盘）
    cn = []
    with src.open(encoding="utf-8") as f:
        for ln in f:
            r = json.loads(ln)
            hs = r.get("headings") or []
            if not hs:
                continue
            cn.append((r["slot"], hs[0].get("raw_name", ""),
                       [h.get("line") or 0 for h in hs], r.get("quad")))

    print(f"=== cn_dun & ordinal PASS: {len(cn)} 份 ===")
    rules = {
        "R1 首标题非法": lambda f, l: r1(f) is False,
        "R2 line 回跳": lambda f, l: r2(l),
        "R3 R1 OR R2": lambda f, l: (r1(f) is False) or r2(l),
        "R4 R1 AND R2": lambda f, l: (r1(f) is False) and r2(l),
        "R5 首标题非标准库首节": lambda f, l: r5(f) is False,
    }
    for name, fn in rules.items():
        hit = [x for x in cn if fn(x[1], x[2])]
        quad = Counter(x[3] for x in hit)
        print(f"  {name:<24} 拦截 {len(hit):>5} ({len(hit)/len(cn)*100:>5.1f}%) "
              f"| A={quad['A']:<5} C={quad['C']:<5}")

    bad_union = [x for x in cn if (r1(x[1]) is False) or r2(x[2])]
    print(f"\n  被 R3 拦截的样例 (前 8):")
    for x in bad_union[:8]:
        print(f"    {x[0]} quad={x[3]} first={x[1][:22]!r} lines={x[2][:8]}")

    # ch_zh 对照样本：从全量里抽样
    os.environ["RUSTFS_ENDPOINT"] = "http://127.0.0.1:9000"
    os.environ["H1_FROZEN_EMIT"] = "0"
    import annual_semi_extraction.rustfs as _r
    _r.ENDPOINT_URL = "http://127.0.0.1:9000"
    _r._server_time_offset = None
    from annual_semi_extraction.rustfs import get_client
    keys = [o["key"] for o in get_client().list_objects(prefix="published/")
            if o["key"].endswith(".md")]
    if limit:
        keys = keys[:limit]
    # 均匀抽样，覆盖全量
    step = max(1, len(keys) // 8000)
    sample_keys = keys[::step][:8000]
    print(f"\n=== ch_zh 对照抽样: {len(sample_keys)} 份 ===")

    tmp_root = tempfile.mkdtemp(prefix="rule_ctrl_")
    ch = []
    try:
        with ProcessPoolExecutor(max_workers=16, initializer=_init,
                                 initargs=("http://127.0.0.1:9000", tmp_root)) as ex:
            for r in ex.map(_work, [(k, tmp_root) for k in sample_keys], chunksize=16):
                if r and r["method"] == "ch_zh" and r["ov"] == "PASS":
                    ch.append((r["slot"], r["first"], r["lines"], "ctrl"))
    finally:
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)

    print(f"  有效 ch_zh & PASS 对照样本: {len(ch)}")
    for name, fn in rules.items():
        hit = [x for x in ch if fn(x[1], x[2])]
        print(f"  {name:<24} 误伤 {len(hit):>5} ({len(hit)/len(ch)*100:>5.2f}%)")
    print("\n  ch_zh 被 R3 误伤的样例 (前 5):")
    for x in [x for x in ch if (r1(x[1]) is False) or r2(x[2])][:5]:
        print(f"    {x[0]} first={x[1][:22]!r} lines={x[2][:8]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
