"""检查 600010_2008_2.md 的一级标题识别是否彻底错了。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("RUSTFS_ENDPOINT", "http://127.0.0.1:9000")
os.environ.setdefault("H1_FROZEN_EMIT", "0")

from annual_semi_extraction.rustfs import get_client  # noqa: E402
from annual_semi_extraction.h1.extractor import extract  # noqa: E402

SLOT = "600010_2008_2"
key = f"published/600010/{SLOT}.md"
client = get_client()
text = client.read_text(key)
lines = text.splitlines()

print("=== 原文前 130 行中含编号/标题的行 ===")
for i, ln in enumerate(lines[:130], 1):
    s = ln.strip()
    if not s:
        continue
    if (s.startswith("#") or s.startswith("第") or s[:2] in ("一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")
            or "有限售" in s or "无限售" in s or "目 录" in s or "目录" in s):
        print(f"  L{i:<4} {s[:100]!r}")

print("\n=== 原文 80-100 行 ===")
for i in range(79, min(101, len(lines)), 1):
    print(f"  L{i+1:<4} {lines[i][:110]!r}")

tmp = Path(tempfile.mkdtemp())
p = tmp / f"{SLOT}.md"
p.write_bytes(text.encode("utf-8"))
rec = extract(p)
p.unlink(missing_ok=True)

print("\n=== extract() 结果 ===")
for k in ("extraction_method", "n_headings", "is_complete_l1", "coverage_ratio",
          "ordinal_valid", "ordinal_verdict", "ordinal_missing", "library_match"):
    print(f"  {k} = {rec.get(k)!r}")
print("  headings:")
for h in rec["headings"]:
    print(f"    ord={h['ordinal']:<3} marker={h.get('marker')!r:<8} "
          f"sys={h.get('numbering_system')!r:<9} raw={h['raw_name']!r:<28} "
          f"can={h.get('canonical_name')!r} cat={h.get('canonical_cat')!r}")

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
