"""全量提取「编号组合」：1. 2. 3. 4. 作为一组。

与之前三个分析单位的根本差别：
- 直接读 **MD 原始字节**（不用已加工的 h1 列表），扫描任意层级的编号行；
- 用**编号重置检测**把连续编号切成 run（连续序列），而不是逐行判层级；
- 组合 = (编号体系, 有序编号序列)，可同时给集合口径；
- 五套编号体系统一归一化（cn/ar 互转、章/节等价、全半角），复用上游能力。

零新增依赖。输出 data/numbering_combos.json。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")

from heading_corpus import cn_to_int, slot_key_from_path  # noqa: E402
from heading_morphology import LEGAL_NAMES  # noqa: E402
from annual_semi.identify._funcs.heading_verify import _map_heading_to_category  # noqa: E402

# 编号体系：name 不以数字开头，避免把 1.1 / 2.3 这类多级编号误当一级
PATTERNS = [
    ("CH_ZH",    re.compile(r"^第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])\s*[:：\.．]?\s*(\D.*)$")),
    ("CN_DUN",   re.compile(r"^([一二三四五六七八九十]{1,3})\s*[、\.．]\s*(\D.*)$")),
    ("AR_DOT",   re.compile(r"^(\d{1,2})\s*[\.．、]\s*(\D.*)$")),
    ("AR_PAREN", re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*(\D.*)$")),
    ("PAREN_CN", re.compile(r"^[（(]\s*([一二三四五六七八九十]{1,3})\s*[）)]\s*(\D.*)$")),
]
RE_H = re.compile(r"^(#{1,6})\s+(.*)$")
RE_MULTILEVEL = re.compile(r"^\d{1,2}\.\d{1,2}")
FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# 长度先验来自法规原文派生清单，不是从语料归纳（E1 外部身份）
_LC_PATH = Path(__file__).resolve().parents[1] / "annual_semi_extraction/spec/legal_chapters.json"
SECTION_COUNTS = {
    k: len(v["sections"])
    for k, v in json.loads(_LC_PATH.read_text(encoding="utf-8"))["chapters"].items()
}


def expected_sections(year: int, period: int) -> int:
    """by_period_end 裁决：2021-2024 适用〔2021〕15号/16号，2025+ 适用〔2025〕3号/4号。"""
    if year <= 2024:
        key = "no2_2021_15" if period == 4 else "no3_2021_16"
    else:
        key = "no2_2025_3" if period == 4 else "no3_2025_4"
    return SECTION_COUNTS[key]


def parse_numbered_line(body: str) -> dict | None:
    """返回 {system, ordinal, name, kind}；非编号行返回 None。"""
    if RE_MULTILEVEL.match(body):
        return None  # 1.1 / 2.3 属子级编号，不进一级 run
    s = body.translate(FULLWIDTH).strip()
    for system, pat in PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        raw_num = m.group(1)
        ordinal = cn_to_int(raw_num)
        if ordinal is None or ordinal < 1 or ordinal > 60:
            return None
        if system == "CH_ZH":
            name = m.group(3).strip()
            kind = m.group(2)
        else:
            name = m.group(2).strip()
            kind = system
        return {"system": system, "ordinal": ordinal, "name": name, "kind": kind}
    return None


def scan_file(path: Path) -> dict | None:
    slot = slot_key_from_path(path)
    if slot is None:
        return None
    _code, _year, _period = slot.split("_")
    legal_n_sections = expected_sections(int(_year), int(_period))
    raw = path.read_bytes()
    items = []
    offset = 0
    for lineno, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        start, end = offset, offset + len(raw_line)
        offset = end
        line = raw_line.decode("utf-8", errors="replace")
        verbatim = line
        body = line.rstrip("\r\n")
        hm = RE_H.match(body)
        md_level = len(hm.group(1)) if hm else 0
        title = hm.group(2).strip() if hm else body.strip()
        if not title:
            continue
        info = parse_numbered_line(title)
        if info is None:
            continue
        items.append({
            "line": lineno, "start": start, "end": end,
            "verbatim": verbatim, "md_level": md_level,
            **info,
        })

    # 按体系分组 → 编号重置检测（ordinal 下降或回到 1 -> 新 run）
    by_system: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_system[it["system"]].append(it)

    runs = []
    for system, seq in by_system.items():
        cur: list[dict] = []
        for it in seq:
            next_ordinal = (cur[-1]["ordinal"] + 1) if cur else 1
            if cur and it["ordinal"] != next_ordinal:
                if len(cur) >= 2:
                    runs.append(_make_run(system, cur, legal_n_sections))
                cur = []
                if it["ordinal"] != 1:
                    # 非从 1 起始的残段，仍记录但标 partial
                    cur = [it]
                    continue
            cur.append(it)
        if len(cur) >= 2:
            runs.append(_make_run(system, cur, legal_n_sections))

    return {
        "slot_key": slot,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "n_bytes": len(raw),
        "n_numbered_lines": len(items),
        "n_runs": len(runs),
        "runs": runs,
    }


def _make_run(system: str, seq: list[dict], expected: int) -> dict:
    ords = [x["ordinal"] for x in seq]
    names = [x["name"] for x in seq]
    # 名称映射到法定节名 / canonical 类别（外部锚）
    legal_hits = []
    cats = []
    for n in names:
        hit = next((ln for ln in LEGAL_NAMES if ln in n), None)
        legal_hits.append(hit or "")
        cat = _map_heading_to_category(n)
        cats.append(cat or "")
    combo = f"{system}:" + ",".join(map(str, ords))
    contiguous = ords == list(range(1, len(ords) + 1))
    levels = sorted({x["md_level"] for x in seq})
    rate = sum(1 for x in legal_hits if x) / len(legal_hits)
    # 候选「一级章节序列」：外部锚筛选器，不是频次筛选器。
    # 长度由 reg_version -> legal_chapters.json 的法定节数给定（±2 容差覆盖 conditional 节）；
    # 且必须是 H1 层、法定名命中过半。三者均可外部复核。
    is_candidate_l1 = bool(
        contiguous and abs(len(ords) - expected) <= 2
        and all(l == 1 for l in levels)
        and rate >= 0.5
    )
    return {
        "system": system,
        "ords": ords,
        "combo": combo,
        "combo_len": len(ords),
        "combo_set": f"{system}:len{len(ords)}",
        "is_candidate_l1": is_candidate_l1,
        "start_line": seq[0]["line"],
        "end_line": seq[-1]["line"],
        "start_offset": seq[0]["start"],
        "end_offset": seq[-1]["end"],
        "names": names[:40],
        "md_levels": sorted({x["md_level"] for x in seq}),
        "legal_hits": legal_hits[:40],
        "legal_hit_rate": round(sum(1 for x in legal_hits if x) / len(legal_hits), 4),
        "canonical_cats": [c for c in dict.fromkeys(cats) if c],
        "is_contiguous_from_1": ords == list(range(1, len(ords) + 1)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/md_cache/published")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/numbering_combos.json")
    args = ap.parse_args()

    files = sorted(Path(args.root).rglob("*.md"))
    if args.limit:
        files = files[: args.limit]
        print(f"调试模式：仅前 {len(files)} 份", flush=True)
    print(f"全量扫描 {len(files)} 份 MD ...", flush=True)

    combo_counter: Counter = Counter()
    combo_stocks: dict[str, set] = defaultdict(set)
    combo_years: dict[str, set] = defaultdict(set)
    combo_periods: dict[str, set] = defaultdict(set)
    combo_legal_rate: dict[str, list] = defaultdict(list)
    system_counter: Counter = Counter()
    run_len_counter: Counter = Counter()
    n_runs_per_doc: Counter = Counter()
    reset_docs = 0
    examples: dict[str, list] = defaultdict(list)
    l1_counter: Counter = Counter()
    l1_by_layer: dict[str, Counter] = defaultdict(Counter)
    l1_stocks: dict[str, set] = defaultdict(set)
    docs_with_l1 = 0
    n_ok = 0

    for i, p in enumerate(files, start=1):
        try:
            rec = scan_file(p)
        except Exception as e:
            print(f"  ERROR {p}: {e}", file=sys.stderr)
            continue
        if rec is None:
            continue
        n_ok += 1
        code, year, period = rec["slot_key"].split("_")
        n_runs_per_doc[rec["n_runs"]] += 1
        by_sys = Counter(r["system"] for r in rec["runs"])
        if any(v > 1 for v in by_sys.values()):
            reset_docs += 1
        has_l1 = False
        for r in rec["runs"]:
            combo = r["combo"]
            system_counter[r["system"]] += 1
            run_len_counter[r["combo_len"]] += 1
            combo_counter[combo] += 1
            combo_stocks[combo].add(code)
            combo_years[combo].add(year)
            combo_periods[combo].add(period)
            combo_legal_rate[combo].append(r["legal_hit_rate"])
            if len(examples[combo]) < 2:
                examples[combo].append({
                    "slot_key": rec["slot_key"], "names": r["names"][:12],
                    "md_levels": r["md_levels"], "legal_hit_rate": r["legal_hit_rate"],
                    "canonical_cats": r["canonical_cats"][:12],
                })
            if r["is_candidate_l1"]:
                has_l1 = True
                l1_counter[combo] += 1
                l1_by_layer[f"{year}_P{period}"][combo] += 1
                l1_stocks[combo].add(code)
        if has_l1:
            docs_with_l1 += 1
        if i % 3000 == 0:
            print(f"  {i}/{len(files)} ...", flush=True)

    top = []
    for combo, cnt in combo_counter.most_common(30):
        rates = combo_legal_rate[combo]
        top.append({
            "combo": combo, "count": cnt,
            "n_stocks": len(combo_stocks[combo]),
            "n_years": len(combo_years[combo]),
            "n_periods": len(combo_periods[combo]),
            "mean_legal_hit_rate": round(sum(rates) / len(rates), 4),
            "examples": examples[combo][:2],
        })

    # 双排名：纯频次 vs 长度加权（短模式频次天然更高）
    by_weighted = sorted(top, key=lambda x: -(x["count"] * (x["combo"].count(",") + 1)))
    l1_top = []
    for combo, cnt in l1_counter.most_common(20):
        l1_top.append({
            "combo": combo, "count": cnt,
            "n_stocks": len(l1_stocks[combo]),
            "by_layer": {k: dict(v.most_common(4)) for k, v in sorted(l1_by_layer.items())},
        })

    out = {
        "n_files": len(files), "n_ok": n_ok,
        "n_runs_total": sum(combo_counter.values()),
        "n_docs_with_reset": reset_docs,
        "n_runs_per_doc": dict(n_runs_per_doc.most_common(15)),
        "system_distribution": system_counter.most_common(),
        "run_len_distribution": run_len_counter.most_common(20),
        "n_unique_combos": len(combo_counter),
        "rank_by_frequency": top,
        "rank_by_legal_alignment": sorted(top, key=lambda y: -y["mean_legal_hit_rate"])[:20],
        "rank_by_length_weighted": [
            {"combo": x["combo"], "count": x["count"],
             "weighted": x["count"] * (x["combo"].count(",") + 1),
             "mean_legal_hit_rate": x["mean_legal_hit_rate"]}
            for x in by_weighted[:15]
        ],
        "candidate_l1": {
            "filter": "contiguous_from_1 AND abs(len - reg_version_expected_sections)<=2 "
                      "AND md_level all==1 AND legal_hit_rate>=0.5",
            "section_counts_by_version": SECTION_COUNTS,
            "n_docs_with_candidate": docs_with_l1,
            "coverage": round(docs_with_l1 / max(1, n_ok), 4),
            "n_unique_combos": len(l1_counter),
            "top20": l1_top,
        },
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成 {n_ok} 份, run 总数 {sum(combo_counter.values())}, 唯一组合 {len(combo_counter)}")
    print(f"有编号重置(同体系多 run)的报告: {reset_docs} ({reset_docs/max(1,n_ok):.1%})")
    print(f"体系分布: {system_counter.most_common()}")
    print(f"run 长度 Top10: {run_len_counter.most_common(10)}")
    print("\n按频次 Top5:")
    for x in top[:5]:
        print(f"  {x['count']:7d} × {x['combo'][:42]:42s} legal={x['mean_legal_hit_rate']:.3f}")
    print("按法规对齐度 Top5:")
    for x in out["rank_by_legal_alignment"][:5]:
        print(f"  legal={x['mean_legal_hit_rate']:.3f} count={x['count']:6d} {x['combo'][:42]}")
    print("\n候选一级章节序列（外部锚筛选后）:")
    print(f"  覆盖 {docs_with_l1}/{n_ok} 份 ({out['candidate_l1']['coverage']:.1%}), "
          f"唯一组合 {len(l1_counter)}")
    for x in l1_top[:5]:
        print(f"  {x['count']:6d} × {x['combo'][:44]:44s} stocks={x['n_stocks']}")
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
