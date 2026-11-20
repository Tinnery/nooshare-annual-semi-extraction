"""独立复核：h1_combo_raw.json 的候选组合是否可能含跳号/重复序号。

不依赖 extract() 的判定字段，从三个角度交叉：
1. 明细中 C 类是否全部 PASS、missing/dupes 为空
2. combos 里每条组合的 headings 样本，直接从 ordinal 序列重算一遍
3. 隐蔽风险：同一 pattern 下是否存在「C 类(合规) + D 类(违规)」混合，
   即组合文本相同但部分文档跳号被排除
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

combo_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/h1_combo_raw.json")
docs_path = Path(sys.argv[2] if len(sys.argv) > 2 else "data/h1_combo_raw_docs.jsonl")

d = json.loads(combo_path.read_text(encoding="utf-8"))
combos = d["combos"]

quad_pat: dict[str, Counter] = defaultdict(Counter)
c_bad = []
quad_count = Counter()
with docs_path.open(encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        q = r["quad"]
        quad_count[q] += 1
        if q in ("C", "D") and r.get("pattern"):
            quad_pat[q][tuple(r["pattern"])] += 1
        if q == "C":
            if (r.get("ordinal_valid") is not True
                    or r.get("ordinal_verdict") != "PASS"
                    or r.get("ordinal_missing")
                    or r.get("ordinal_duplicates")):
                c_bad.append(r)

print("=== 1. C 类逐文档判定 ===")
print(f"  C 类文档 {quad_count['C']}，判定不合规的: {len(c_bad)} (应为 0)")
print(f"  D 类(序号违规被排除) 文档: {quad_count['D']}")

print("\n=== 2. combos 的 headings 样本独立重算序号 ===")
def seq_check(headings):
    ords = [h["ordinal"] for h in headings if (h.get("ordinal") or 0) > 0]
    n = len(ords)
    if n == 0:
        return "NO_NUMBERED", []
    dupes = sorted({o for o in ords if ords.count(o) > 1})
    missing = sorted(set(range(1, max(ords) + 1)) - set(ords))
    if dupes:
        return "DUPLICATE", dupes
    if missing:
        return "GAP", missing
    return "PASS", []

bad_samples = []
verdicts = Counter()
zero_count = 0
for c in combos:
    v, detail = seq_check(c["headings"])
    verdicts[v] += 1
    zero_count += sum(1 for h in c["headings"] if (h.get("ordinal") or 0) == 0)
    if v != "PASS":
        bad_samples.append((c["pattern"][:2], c["count"], v, detail))
    if c.get("ordinal_valid") is not True:
        bad_samples.append((c["pattern"][:2], c["count"], "flag_not_true", []))

print(f"  组合总数 {len(combos)}，序号判定分布: {dict(verdicts)}")
print(f"  ordinal_valid 字段非 true / 序号违规的组合: {len(bad_samples)} (应为 0)")
for s in bad_samples[:5]:
    print("   ", s)
print(f"  样本 headings 中 ordinal=0 的无编号标题总数: {zero_count}（规则明确不参与序列）")

print("\n=== 3. 同 pattern 下 C/D 混合检查 ===")
c_pats = set(quad_pat["C"])
d_pats = set(quad_pat["D"])
mixed = c_pats & d_pats
print(f"  C 类 pattern 数 {len(c_pats)} | D 类 pattern 数 {len(d_pats)}")
print(f"  交集(同文本序列既有合规又有跳号): {len(mixed)}")
combo_pats = {tuple(c["pattern"]) for c in combos}
print(f"  combos 中的 pattern 是否全部来自 C 类: {combo_pats <= c_pats}")
print(f"  combos 里混入了 D 类独占 pattern: {len(combo_pats & (d_pats - c_pats))}")
if mixed:
    print("\n  混合 pattern 样例（count 只计合规文档）:")
    cm = {tuple(c["pattern"]): c["count"] for c in combos}
    for p in sorted(mixed, key=lambda p: -cm.get(p, 0))[:5]:
        print(f"    C={quad_pat['C'][p]:<5} D={quad_pat['D'][p]:<4} "
              f"combo_count={cm.get(p)} p0={p[0][:26]!r}")

count_sum = sum(c["count"] for c in combos)
print("\n=== 结论 ===")
print(f"  sum(combos.count)={count_sum} | C 类文档={quad_count['C']} "
      f"{'一致' if count_sum == quad_count['C'] else '不一致'}")
ok = (not c_bad and not bad_samples and combo_pats <= c_pats
      and not (combo_pats & (d_pats - c_pats)) and count_sum == quad_count["C"]
      and verdicts.get("PASS") == len(combos))
print("  ", "PASS 候选组合不含跳号/重复序号" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
