"""一级标题候选语料的测量学分析（零新增依赖）。

产出对应四段式中的「专业方法」实证：
1. 分析单位对比：原始 H1 / 编号型 / canonical 三种单位下的组合分布
2. 伪重复修正：模板族聚类 + Simpson 有效样本量
3. 物种丰富度：Chao1(bias-corrected) + bootstrap 置信区间
4. 饱和曲线：累积样本 → 边际新增类型数
5. codebook 归纳：H1 文本频次 → 结构型/非结构型判据草案
6. 失败分类学：按 (year, period, source) 分层的错误类型
7. leave-one-out：高频组合的边际覆盖贡献
8. 近邻反例：标题变体的最小编辑距离对
9. 判别对：同 slot 多 source MD 的 Jaccard 距离
10. 残差集：未被高频组合覆盖的报告

不产出任何「合规率」结论（01 §五.3：全量只证明没崩）。
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, r"C:\dev\nooshare-annual-semi")

RE_SLOT = re.compile(r"^(\d{6})_(\d{4})_([24])$")


def load_db_meta() -> dict:
    """交付表元数据（模板族去冗余的关键）；离线时返回空。"""
    try:
        from annual_semi.db._conn import connect
        c = connect()
        cur = c.cursor()
        cur.execute("""
            SELECT stock_code, report_year, period, winner_source,
                   selection_rule, candidate_count, fingerprint, content_sha256
            FROM annual_semi.reconciled_report
            WHERE period IN (2,4) AND report_year BETWEEN 2021 AND 2024
        """)
        out = {
            f"{r[0]}_{r[1]}_{r[2]}": {
                "winner_source": r[3], "selection_rule": r[4],
                "candidate_count": r[5], "fingerprint": r[6],
                "content_sha256": r[7],
            }
            for r in cur.fetchall()
        }
        c.close()
        return out
    except Exception as e:
        print(f"  [warn] DB 元数据不可用，降级为 slot_key 内部分层: {e}", file=sys.stderr)
        return {}


def chao1(freqs: Counter) -> dict:
    """Chao1 bias-corrected + 经典方差；f1/f2 为 singleton/doubleton 物种数。"""
    s_obs = len(freqs)
    f1 = sum(1 for v in freqs.values() if v == 1)
    f2 = sum(1 for v in freqs.values() if v == 2)
    est = s_obs + (f1 * (f1 - 1)) / (2 * (f2 + 1))
    # 经典 Chao1 方差（f2>0 时）
    if f2 > 0:
        r = f1 / f2
        var = f2 * (0.25 * r**4 + r**3 + 0.5 * r**2)
    else:
        var = float("nan")
    return {
        "s_obs": s_obs, "singletons": f1, "doubletons": f2,
        "chao1_est": round(est, 2), "unseen_est": round(est - s_obs, 2),
        "var": None if math.isnan(var) else round(var, 2),
    }


def bootstrap_saturation(units: list[str], points: int = 12, seed: int = 42) -> list[dict]:
    """累积样本 → 观测类型数（bootstrap 给 95% 区间）。"""
    rng = random.Random(seed)
    n = len(units)
    curve = []
    for i in range(1, points + 1):
        k = max(1, round(n * i / points))
        # 重复 30 次重采样估计区间
        vals = []
        for _ in range(30):
            sample = rng.choices(units, k=k)
            vals.append(len(set(sample)))
        vals.sort()
        curve.append({
            "n_reports": k,
            "observed_types": len(set(units[:k])),
            "boot_mean": round(sum(vals) / len(vals), 1),
            "boot_lo": vals[1], "boot_hi": vals[-2],
        })
    return curve


def jaccard(a: set, b: set) -> float:
    u = a | b
    return 0.0 if not u else len(a ^ b) / len(u)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/heading_corpus.jsonl")
    ap.add_argument("--out", default="data/heading_analysis.json")
    args = ap.parse_args()

    rows = []
    with Path(args.corpus).open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"载入 {len(rows)} 份报告", flush=True)

    meta = load_db_meta()
    print(f"DB 元数据: {len(meta)} 条", flush=True)

    # ── 1. 分析单位对比 ────────────────────────────────────────────
    units = {}
    for key in ("fp_h1", "fp_numbered", "fp_canonical"):
        c = Counter(r[key] for r in rows)
        units[key] = {
            "n_unique": len(c),
            "top5": [{"fp": k, "count": v} for k, v in c.most_common(5)],
            "top1_share": round(c.most_common(1)[0][1] / len(rows), 4),
            "chao1": chao1(c),
        }

    # ── 2. 伪重复 / 有效样本量 ─────────────────────────────────────
    fp_c = Counter(r["fp_canonical"] for r in rows)
    p = [v / len(rows) for v in fp_c.values()]
    simpson_eff = 1 / sum(x * x for x in p)
    shannon = -sum(x * math.log(x) for x in p if x > 0)
    by_source = Counter(
        (meta.get(r["slot_key"], {}).get("winner_source", "UNKNOWN"),
         r["fp_canonical"])
        for r in rows
    )
    # 模板族 = (winner_source, canonical组合)；有效数
    fam = Counter((meta.get(r["slot_key"], {}).get("winner_source", "UNKNOWN"),
                   meta.get(r["slot_key"], {}).get("selection_rule", "UNKNOWN"))
                  for r in rows)
    pseudo = {
        "n_reports": len(rows),
        "n_canonical_combos": len(fp_c),
        "simpson_effective_types": round(simpson_eff, 2),
        "shannon_H": round(shannon, 3),
        "top1_share": round(max(p), 4),
        "source_rule_families": [{"family": list(k), "count": v} for k, v in fam.most_common(10)],
        "note": "原始报告数远大于有效独立类型数；置信界必须按有效样本量计算",
    }

    # ── 3. 物种丰富度（对三种单位） ─────────────────────────────────
    richness = {
        k: units[k]["chao1"] for k in units
    }

    # ── 4. 饱和曲线 ────────────────────────────────────────────────
    curve = bootstrap_saturation([r["fp_canonical"] for r in rows])

    # ── 5. codebook 归纳：H1 文本频次 ───────────────────────────────
    h1_text = Counter()
    h1_numbered = Counter()
    for r in rows:
        for h in r["h1"]:
            h1_text[h["text"]] += 1
        for n in r["numbered"]:
            h1_numbered[n["name"]] += 1
    # 结构型 = 带编号 marker 的 H1；非结构型 = 其余
    codebook_seed = {
        "top_nonstructural_h1": [
            {"text": t, "count": c} for t, c in h1_text.most_common(40)
            if not re.search(r"第\s*[一二三四五六七八九十百零〇0-9]+\s*[章节]", t)
        ][:25],
        "top_numbered_names": [
            {"name": t, "count": c} for t, c in h1_numbered.most_common(30)
        ],
        "n_distinct_h1_text": len(h1_text),
        "n_distinct_numbered_names": len(h1_numbered),
    }

    # ── 6. 失败分类学（分层） ───────────────────────────────────────
    core = {"company_profile", "mda", "shares", "matters", "financial"}
    layers = defaultdict(lambda: Counter())
    for r in rows:
        m = RE_SLOT.match(r["slot_key"])
        if not m:
            continue
        yr, per = m.group(2), m.group(3)
        src = meta.get(r["slot_key"], {}).get("winner_source", "UNKNOWN")
        layer = f"{yr}_P{per}|{src}"
        sig = set(r["canonical_signature"])
        if r["n_h1"] == 0:
            layers[layer]["NO_H1_PLAINTEXT"] += 1
        if not r["numbered"]:
            layers[layer]["NO_NUMBERED_HEADING"] += 1
        if sig and (core - sig):
            layers[layer]["CORE_SECTION_MISSING"] += 1
        if r["n_crossref"] > 0:
            layers[layer]["HAS_CROSSREF_NOISE"] += 1
        # 编号连续性
        ords = [n["ordinal"] for n in r["numbered"] if n["ordinal"]]
        if ords and ords != list(range(1, len(ords) + 1)):
            layers[layer]["ORDINAL_NOT_CONTIGUOUS"] += 1
        layers[layer]["TOTAL"] += 1
    taxonomy = {k: dict(v) for k, v in sorted(layers.items())}

    # ── 7. leave-one-out ───────────────────────────────────────────
    loo = []
    for fp, cnt in fp_c.most_common(10):
        rest = Counter({k: v for k, v in fp_c.items() if k != fp})
        loo.append({
            "fp": fp, "covers": cnt,
            "coverage_share": round(cnt / len(rows), 4),
            "residual_after_removal": len(rows) - cnt,
            "remaining_types": len(rest),
        })

    # ── 8. near-miss 反例（标题变体最小编辑距离） ───────────────────
    names = [t for t, c in h1_numbered.most_common(60) if len(t) >= 3]
    near = []
    for i, a in enumerate(names[:30]):
        for b in names[i + 1:]:
            if a == b or abs(len(a) - len(b)) > 2:
                continue
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if 0.75 <= ratio < 1.0:
                near.append({"a": a, "b": b, "similarity": round(ratio, 3)})
        if len(near) >= 25:
            break
    near.sort(key=lambda x: -x["similarity"])

    # ── 9. 判别对：同 slot 多 source MD ────────────────────────────
    pairs = []
    structured_root = Path("data/md_cache/structured")
    pub_root = Path("data/md_cache/published")
    if structured_root.exists():
        from heading_corpus import extract_one, slot_key_from_path  # 同目录
        # 建立 published slot 索引（只读已有缓存）
        pub_index = {}
        for p in pub_root.rglob("*.md"):
            s = slot_key_from_path(p)
            if s:
                pub_index.setdefault(s, []).append(p)
        for p in structured_root.rglob("*.md"):
            s = slot_key_from_path(p)
            # hash 命名或 2021Q4 命名 → 用目录名 + 文件名推断
            if not s:
                m = re.match(r"^(\d{6})_(\d{4})Q([24])\.md$", p.name)
                if m:
                    s = f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
            if not s or s not in pub_index:
                continue
            try:
                alt = extract_one(p)
                base = extract_one(pub_index[s][0])
                if alt is None or base is None:
                    continue
                d = jaccard(set(alt["canonical_signature"]), set(base["canonical_signature"]))
                pairs.append({
                    "slot_key": s, "alt_path": str(p),
                    "jaccard_distance": round(d, 3),
                    "verdict": "DIVERGENT" if d > 0.3 else "CONSISTENT",
                    "alt_sig": alt["canonical_signature"],
                    "base_sig": base["canonical_signature"],
                })
            except Exception as e:
                pairs.append({"slot_key": s, "alt_path": str(p), "error": str(e)})
    pair_summary = {
        "n_pairs": len(pairs),
        "n_divergent": sum(1 for x in pairs if x.get("verdict") == "DIVERGENT"),
        "threshold": 0.3,
        "pairs": pairs,
    }

    # ── 10. 残差集 ─────────────────────────────────────────────────
    hi = {k for k, v in fp_c.items() if v >= max(5, len(rows) * 0.001)}
    residual = [r["slot_key"] for r in rows if r["fp_canonical"] not in hi]
    residual_summary = {
        "n_high_freq_combos": len(hi),
        "n_residual_reports": len(residual),
        "residual_share": round(len(residual) / len(rows), 4),
        "sample": residual[:40],
    }

    out = {
        "n_reports": len(rows),
        "analysis_units": units,
        "pseudoreplication": pseudo,
        "richness": richness,
        "saturation_curve": curve,
        "codebook_seed": codebook_seed,
        "error_taxonomy_by_layer": taxonomy,
        "leave_one_out": loo,
        "near_miss_pairs": near[:25],
        "discriminant_pairs": pair_summary,
        "residual": residual_summary,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写出 {args.out}")
    print(f"分析单位唯一组合数: " + ", ".join(f"{k}={v['n_unique']}" for k, v in units.items()))
    print(f"Chao1(canonical): {richness['fp_canonical']}")
    print(f"有效类型数(Simpson): {pseudo['simpson_effective_types']} / 报告 {len(rows)}")
    print(f"判别对: {pair_summary['n_pairs']} 组, 分歧 {pair_summary['n_divergent']}")
    print(f"残差集: {residual_summary['n_residual_reports']} 份 ({residual_summary['residual_share']:.1%})")


if __name__ == "__main__":
    main()
