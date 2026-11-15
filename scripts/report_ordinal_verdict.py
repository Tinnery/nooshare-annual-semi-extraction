"""用 extractor.ordinal_verdict 对全量抽取结果重算判定分布。"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from annual_semi_extraction.h1.extractor import ordinal_verdict  # noqa: E402

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/h1_full.jsonl")
total = 0
verdict = Counter()
by_method: dict[str, Counter] = defaultdict(Counter)
missing_pos = Counter()
samples: dict[str, list[str]] = defaultdict(list)

with src.open(encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        total += 1
        v = ordinal_verdict(r.get("headings") or [])
        k = v["ordinal_verdict"]
        verdict[k] += 1
        by_method[r.get("extraction_method", "?")][k] += 1
        for m in v["ordinal_missing"]:
            missing_pos[m] += 1
        if k != "PASS" and len(samples[k]) < 4:
            samples[k].append(
                f"{r.get('slot_key')} n={v['ordinal_n']} "
                f"missing={v['ordinal_missing']} dupes={v['ordinal_duplicates']}"
            )

print(f"输入: {src} | 记录数: {total}")
print("\n=== 判定分布 ===")
for k, v in verdict.most_common():
    print(f"  {k:<16}{v:>8}  {v/total*100:>6.2f}%")
print("\n=== 按 extraction_method ===")
for m, c in sorted(by_method.items(), key=lambda x: -sum(x[1].values())):
    print(f"  {m:<14} n={sum(c.values()):<7} {dict(c)}")
print("\n=== 缺失序号频次（不豁免任何数字）===")
for k, v in sorted(missing_pos.items()):
    print(f"  缺 {k:>2}: {v}")
print("\n=== 违规样本 ===")
for k, ss in samples.items():
    for s in ss:
        print(f"  [{k}] {s}")
