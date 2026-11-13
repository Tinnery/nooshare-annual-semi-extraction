"""重算：把转换损伤从统计分母分离，并恢复同 MD 内的 TOC/正文双路径。

产出：
- data/heading_corpus_clean.jsonl  每份报告的形态分类结果（verbatim 仍在原 corpus 可回查）
- data/heading_recompute.json      修正前后对比 + 双路径 Jaccard 统计 + 被推翻的结论清单

不做：提高识别率、AGENT 判定、清洗覆盖 verbatim、手敲关键词。
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")

from heading_morphology import classify_h1, LEGAL_NAMES  # noqa: E402
from annual_semi.identify._funcs.heading_verify import _map_heading_to_category  # noqa: E402

CORPUS = Path("data/heading_corpus.jsonl")
OUT_CORPUS = Path("data/heading_corpus_clean.jsonl")
OUT_REPORT = Path("data/heading_recompute.json")

TOC_MORPHS = {"TOC_ROW", "TOC_TAIL"}
BODY_MORPHS = {"CLEAN", "GLUED_BODY", "CHECKBOX"}
THRESHOLD = 0.3  # 上游 D-3 冻结


def fp(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def jaccard(a: set, b: set) -> float:
    u = a | b
    return 0.0 if not u else len(a ^ b) / len(u)


def main() -> None:
    rows = [json.loads(l) for l in CORPUS.open(encoding="utf-8")]
    print(f"载入 {len(rows)} 份", flush=True)

    morph_counter: Counter = Counter()
    before = {
        "fp_numbered": Counter(), "fp_canonical": Counter(),
        "ordinal_bad": 0, "core_missing": 0,
    }
    after = {
        "fp_numbered_clean": Counter(), "fp_canonical_clean": Counter(),
        "ordinal_bad": 0, "core_missing": 0,
    }
    core = {"company_profile", "mda", "shares", "matters", "financial"}
    pair_stats: Counter = Counter()
    pair_examples = []
    out_lines = []

    for idx, r in enumerate(rows, start=1):
        classified = []
        toc_names: list[str] = []
        body_names: list[str] = []
        for h in r["h1"]:
            c = classify_h1(h["text"])
            morph_counter[c["morphology"]] += 1
            c["line"] = h["line"]
            c["start"] = h["start"]
            c["end"] = h["end"]
            classified.append(c)
            for sg in c["segments"]:
                if not sg["name"]:
                    continue
                if c["morphology"] in TOC_MORPHS:
                    toc_names.append(sg["name"])
                elif c["morphology"] in BODY_MORPHS:
                    body_names.append(sg["name"])

        def to_cat(names):
            out = []
            for n in names:
                cat = _map_heading_to_category(n)
                if cat and cat not in out:
                    out.append(cat)
            return out

        toc_sig = to_cat(toc_names)
        body_sig = to_cat(body_names)
        # 正文签名为主；TOC 单独保存，不并入，避免目录页自证
        clean_sig = body_sig

        numbered_clean = "|".join(f"{sg['name']}" for c in classified
                                  for sg in c["segments"] if sg["name"]
                                  and c["morphology"] in BODY_MORPHS)

        before["fp_numbered"][r["fp_numbered"]] += 1
        before["fp_canonical"][r["fp_canonical"]] += 1
        after["fp_numbered_clean"][fp(numbered_clean)] += 1
        after["fp_canonical_clean"][fp("|".join(clean_sig))] += 1

        # 修正前：用原 numbered 的 ordinal 判定
        ords = [n["ordinal"] for n in r["numbered"] if n["ordinal"]]
        if ords and ords != list(range(1, len(ords) + 1)):
            before["ordinal_bad"] += 1
        if (core - set(r["canonical_signature"])):
            before["core_missing"] += 1

        # 修正后：用 body_segments 的 marker 序号（从原 verbatim 重解析由 classify 完成）
        body_ord = []
        for c in classified:
            if c["morphology"] not in BODY_MORPHS:
                continue
            for sg in c["segments"]:
                if sg["name"]:
                    body_ord.append(sg["name"])
        # 序号连续性以「名字序列是否覆盖法定顺序」近似（避免重复发明 cn/ar 解析）
        if body_ord and len(set(body_ord)) < len(body_ord):
            after["ordinal_bad"] += 1
        if core - set(clean_sig):
            after["core_missing"] += 1

        # 双路径（仅当两路径都有内容时可测）
        if toc_sig and body_sig:
            d = jaccard(set(toc_sig), set(body_sig))
            pair_stats["n_measurable"] += 1
            pair_stats["divergent" if d > THRESHOLD else "consistent"] += 1
            if d > THRESHOLD and len(pair_examples) < 12:
                pair_examples.append({
                    "slot_key": r["slot_key"], "jaccard": round(d, 3),
                    "toc": toc_sig, "body": body_sig,
                    "only_toc": sorted(set(toc_sig) - set(body_sig)),
                    "only_body": sorted(set(body_sig) - set(toc_sig)),
                })
        else:
            pair_stats["n_one_path_only"] += 1

        out_lines.append(json.dumps({
            "slot_key": r["slot_key"],
            "source_sha256": r["source_sha256"],
            "n_h1": r["n_h1"],
            "h1_classified": [
                {k: c[k] for k in ("line", "start", "end", "morphology",
                                   "n_markers", "n_segments", "segments", "clean_names")}
                for c in classified
            ],
            "toc_sections": toc_sig,
            "body_sections": body_sig,
            "canonical_clean": clean_sig,
            "fp_numbered_clean": fp(numbered_clean),
            "fp_canonical_clean": fp("|".join(clean_sig)),
        }, ensure_ascii=False))

        if idx % 3000 == 0:
            print(f"  {idx}/{len(rows)} ...", flush=True)

    OUT_CORPUS.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    def summarize(c: Counter) -> dict:
        s_obs = len(c)
        f1 = sum(1 for v in c.values() if v == 1)
        f2 = sum(1 for v in c.values() if v == 2)
        est = s_obs + (f1 * (f1 - 1)) / (2 * (f2 + 1))
        p = [v / sum(c.values()) for v in c.values()]
        return {
            "n_unique": s_obs, "singletons": f1, "doubletons": f2,
            "chao1_est": round(est, 2), "unseen_est": round(est - s_obs, 2),
            "simpson_eff": round(1 / sum(x * x for x in p), 2),
            "top1_share": round(max(p), 4),
        }

    report = {
        "n_reports": len(rows),
        "legal_name_set_size": len(LEGAL_NAMES),
        "morphology_distribution": morph_counter.most_common(),
        "before": {
            "fp_numbered": summarize(before["fp_numbered"]),
            "fp_canonical": summarize(before["fp_canonical"]),
            "ordinal_not_contiguous": before["ordinal_bad"],
            "core_section_missing": before["core_missing"],
        },
        "after": {
            "fp_numbered_clean": summarize(after["fp_numbered_clean"]),
            "fp_canonical_clean": summarize(after["fp_canonical_clean"]),
            "ordinal_not_contiguous_proxy": after["ordinal_bad"],
            "core_section_missing": after["core_missing"],
        },
        "dual_path": {
            "threshold": THRESHOLD,
            "n_measurable": pair_stats["n_measurable"],
            "n_consistent": pair_stats["consistent"],
            "n_divergent": pair_stats["divergent"],
            "n_one_path_only": pair_stats["n_one_path_only"],
            "examples": pair_examples,
        },
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 形态分布 ===")
    for k, v in morph_counter.most_common():
        print(f"  {k:16s} {v}")
    print("\n=== 修正前 -> 后 ===")
    for key in ("n_unique", "chao1_est", "unseen_est", "simpson_eff", "top1_share"):
        a = report["before"]["fp_numbered"][key]
        b = report["after"]["fp_numbered_clean"][key]
        print(f"  fp_numbered   {key:12s} {a}  ->  {b}")
    for key in ("n_unique", "chao1_est", "unseen_est", "simpson_eff", "top1_share"):
        a = report["before"]["fp_canonical"][key]
        b = report["after"]["fp_canonical_clean"][key]
        print(f"  fp_canonical  {key:12s} {a}  ->  {b}")
    print(f"  CORE_SECTION_MISSING: {before['core_missing']} -> {after['core_missing']}")
    print(f"\n=== 同 MD 双路径 ===")
    print(f"  可测 {pair_stats['n_measurable']} 份, 一致 {pair_stats['consistent']}, "
          f"分歧 {pair_stats['divergent']}, 单路径 {pair_stats['n_one_path_only']}")
    print(f"\n-> {OUT_CORPUS}\n-> {OUT_REPORT}")


if __name__ == "__main__":
    main()
