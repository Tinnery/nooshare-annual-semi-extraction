"""检验「E1 完备性判定是否必须依赖一级标题识别」。

比较两种判定路径在同一批报告上的分歧：
- 路径 A（标题法）：canonical 签名中是否含 core sections
- 路径 B（内容锚点法，不依赖标题）：法定节关键词在**非标题行**的正文出现次数

若大量报告「A 判缺、B 判有」，说明标题法存在系统性漏报，
把 NOT_DISCLOSED 建立在标题识别上会制造假违规。

零新增依赖；输出 data/chapter_necessity.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from heading_corpus import extract_one  # 同目录

# 法定节 → 正文内容锚点（从 legal_chapters.json 节名派生 + 实报同义词）
# 只取 5 个 core sections（与上游 _CORE_SECTIONS 对齐）
ANCHORS = {
    "company_profile": ["公司简介", "公司基本情况", "主要会计数据", "主要财务指标", "本行简介"],
    "mda": ["管理层讨论与分析", "经营情况讨论与分析", "董事会报告", "报告期内公司从事"],
    "shares": ["股份变动", "股东情况", "股本变动", "前 10 名股东", "前十名股东"],
    "matters": ["重要事项", "重大事项", "关联交易", "重大诉讼"],
    "financial": ["财务报告", "财务报表", "审计报告", "资产负债表", "合并资产负债表"],
}
CORE = set(ANCHORS)

RE_H_LINE = re.compile(r"^#{1,6}\s")


def content_anchors(text: str) -> dict[str, int]:
    """统计每个 core section 的锚点在**非标题行**的出现次数。"""
    counts = {k: 0 for k in ANCHORS}
    for line in text.splitlines():
        if RE_H_LINE.match(line):
            continue  # 排除标题行，避免目录/标题自证
        for sec, words in ANCHORS.items():
            if any(w in line for w in words):
                counts[sec] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/heading_corpus.jsonl")
    ap.add_argument("--sample", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min_hits", type=int, default=2,
                    help="非标题行锚点出现次数 >= 此值才判「正文有内容」")
    ap.add_argument("--out", default="data/chapter_necessity.json")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.corpus).open(encoding="utf-8")]
    rng = random.Random(args.seed)
    sample = rows if args.sample >= len(rows) else rng.sample(rows, args.sample)
    print(f"抽样 {len(sample)} / {len(rows)} 份", flush=True)

    confusion = Counter()
    per_section = defaultdict(Counter)
    disagreements = []
    n_read = 0

    for i, r in enumerate(sample, start=1):
        p = Path(r["path"])
        if not p.exists():
            confusion["MISSING_FILE"] += 1
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        n_read += 1
        sig = set(r["canonical_signature"])
        cnt = content_anchors(text)
        for sec in CORE:
            a = sec in sig                       # 标题法：存在
            b = cnt[sec] >= args.min_hits         # 内容法：存在
            key = f"A{int(a)}_B{int(b)}"
            confusion[key] += 1
            per_section[sec][key] += 1
            if not a and b and len(disagreements) < 40:
                disagreements.append({
                    "slot_key": r["slot_key"], "section": sec,
                    "nonheading_hits": cnt[sec],
                    "n_h1": r["n_h1"], "n_numbered": len(r["numbered"]),
                })
        if i % 300 == 0:
            print(f"  {i}/{len(sample)} ...", flush=True)

    # 关键指标
    a0b1 = confusion["A0_B1"]   # 标题法判缺、正文有内容 → 标题法漏报
    a1b0 = confusion["A1_B0"]   # 标题法判有、正文无内容 → 标题法虚报
    total = sum(v for k, v in confusion.items() if k.startswith("A"))
    by_sec = {
        s: {
            "A0_B1_leak": c["A0_B1"],
            "A1_B0_false": c["A1_B0"],
            "leak_rate_among_A0": round(c["A0_B1"] / max(1, c["A0_B1"] + c["A0_B0"]), 4),
        }
        for s, c in per_section.items()
    }
    out = {
        "n_sample": len(sample), "n_read": n_read, "seed": args.seed,
        "min_hits": args.min_hits,
        "confusion": dict(confusion),
        "n_section_pairs": total,
        "title_method_miss_but_content_present": a0b1,
        "title_method_present_but_content_absent": a1b0,
        "leak_rate_among_all_A0": round(a0b1 / max(1, a0b1 + confusion["A0_B0"]), 4),
        "disagreement_rate": round((a0b1 + a1b0) / max(1, total), 4),
        "by_section": by_sec,
        "disagreement_examples": disagreements,
        "interpretation": (
            "A0_B1 = 标题签名未识别到该节，但正文非标题行有 >=min_hits 次内容锚点。"
            "若该值显著，则以一级标题识别为前提的 E1 判定会系统性制造假 NOT_DISCLOSED。"
        ),
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n混淆矩阵: {dict(confusion)}")
    print(f"标题法判缺但正文有内容 (A0_B1): {a0b1} / {total} 节对")
    print(f"其中占所有 A0 的比例: {out['leak_rate_among_all_A0']:.1%}")
    print(f"标题法判有但正文无内容 (A1_B0): {a1b0}")
    print(f"总分歧率: {out['disagreement_rate']:.1%}")
    print("分节:")
    for s, v in by_sec.items():
        print(f"  {s}: 漏报 {v['A0_B1_leak']}, 虚报 {v['A1_B0_false']}, A0中漏报率 {v['leak_rate_among_A0']:.1%}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
