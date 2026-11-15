"""第二步：抽查 cn_dun&PASS 文档 headings 的 md_level / line 特征。

重点验证三个候选信号能否区分「真一级标题」与「表格行混入」：
  S1 md_level 是否混用（0/1）
  S2 line 是否单调递增（目录页在前、正文表格在后 → 会出现回跳）
  S3 首标题 ordinal=1 的 raw_name 是否为合法首节名
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher  # noqa: E402
from annual_semi_extraction.h1.morphology import LEGAL_NAMES  # noqa: E402

src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/cn_dun_audit.jsonl")
m = get_pattern_matcher()
m._load()
standard_titles = set(m._title_set) | set(LEGAL_NAMES)

# 合法「首节名」：标准库里所有 pattern 的第 0 项 + 常见首节词
first_titles = {d["pattern"][0] for d in m._patterns.values()}
print(f"标准库 35 条 pattern 的首标题集合: {sorted(first_titles)}")
print(f"锚定词表 {len(m._title_set)} | 法规有限集 {len(LEGAL_NAMES)}\n")

total = 0
md_mix = 0
md_all0 = 0
md_all1 = 0
line_monotonic = 0
line_nonmono = 0
line_span = Counter()
first_ok = 0
first_bad_samples = []
nonmono_samples = []
mixed_samples = []
first_title_counter = Counter()

with src.open(encoding="utf-8") as f:
    for ln in f:
        r = json.loads(ln)
        hs = r.get("headings") or []
        if not hs:
            continue
        total += 1
        levels = [h.get("md_level") for h in hs]
        lines = [h.get("line") or 0 for h in hs]

        if len(set(levels)) > 1:
            md_mix += 1
            if len(mixed_samples) < 5:
                mixed_samples.append((r["slot"], levels, [h["raw_name"][:12] for h in hs[:4]]))
        elif all(x == 0 for x in levels):
            md_all0 += 1
        elif all(x == 1 for x in levels):
            md_all1 += 1

        mono = all(lines[i] <= lines[i + 1] for i in range(len(lines) - 1))
        if mono:
            line_monotonic += 1
        else:
            line_nonmono += 1
            if len(nonmono_samples) < 6:
                nonmono_samples.append((r["slot"], lines[:10],
                                       [h["raw_name"][:12] for h in hs[:4]]))
        line_span["max-min"] = line_span.get("max-min", 0)
        line_span["sum_span"] = line_span.get("sum_span", 0) + (max(lines) - min(lines))

        first = hs[0].get("raw_name", "")
        first_title_counter[first] += 1
        if first in first_titles or first in standard_titles:
            first_ok += 1
        elif len(first_bad_samples) < 8:
            first_bad_samples.append((r["slot"], first, r.get("quad")))

print(f"=== 明细样本数: {total} ===")
print("\n[S1] md_level 分布")
print(f"  全 0: {md_all0} ({md_all0/total*100:.1f}%) | 全 1: {md_all1} "
      f"({md_all1/total*100:.1f}%) | 混用: {md_mix} ({md_mix/total*100:.1f}%)")
for s in mixed_samples:
    print("   混用样例:", s)

print("\n[S2] line 单调性（按 ordinal 顺序）")
print(f"  单调递增: {line_monotonic} ({line_monotonic/total*100:.1f}%) | "
      f"回跳: {line_nonmono} ({line_nonmono/total*100:.1f}%)")
print(f"  平均 line 跨度: {line_span['sum_span']/total:.1f}")
for s in nonmono_samples:
    print("   回跳样例:", s)

print("\n[S3] 首标题(ordinal=1) 是否为标准库首节名/法规词")
print(f"  合法: {first_ok} ({first_ok/total*100:.1f}%) | "
      f"非法: {total-first_ok} ({(total-first_ok)/total*100:.1f}%)")
for s in first_bad_samples:
    print("   非法样例:", s)
print("\n  Top 12 首标题:")
for t, c in first_title_counter.most_common(12):
    mark = "OK" if (t in first_titles or t in standard_titles) else "BAD"
    print(f"    {mark:<4} {c:<6} {t!r}")

print("\n=== 用户样本 600010_2008_2 对照 ===")
with src.open(encoding="utf-8") as f:
    for ln in f:
        r = json.loads(ln)
        if r["slot"] == "600010_2008_2":
            hs = r["headings"]
            print("  levels:", [h["md_level"] for h in hs])
            print("  lines :", [h["line"] for h in hs])
            print("  names :", [h["raw_name"] for h in hs])
            break
