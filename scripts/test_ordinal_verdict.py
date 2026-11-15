"""ordinal_verdict 规则单元测试：不跳号、不重复，缺任何序号一视同仁。"""
from __future__ import annotations

from annual_semi_extraction.h1.extractor import ordinal_verdict


def hs(ords):
    return [{"ordinal": o, "raw_name": f"t{o}"} for o in ords]


CASES = [
    ("1..7 连续", [1, 2, 3, 4, 5, 6, 7], "PASS", [], []),
    ("1..10 连续", list(range(1, 11)), "PASS", [], []),
    ("缺 8/9（条件章也不豁免）", [1, 2, 3, 4, 5, 6, 7, 10], "GAP", [8, 9], []),
    ("缺 1 / 从2开始", [2, 3, 4, 5, 6, 7, 8, 9, 10], "GAP", [1], []),
    ("缺 4", [1, 2, 3, 5, 6, 7], "GAP", [4], []),
    ("缺 2,4,5", [1, 3, 6, 7, 8, 9, 10], "GAP", [2, 4, 5], []),
    ("尾部跳号 [1..10,13]", list(range(1, 11)) + [13], "GAP", [11, 12], []),
    ("重复", [1, 2, 2, 3, 4], "DUPLICATE", [], [2]),
    ("多个重复", [1, 1, 2, 3, 3], "DUPLICATE", [], [1, 3]),
    ("重复且跳号（两类都报）", [1, 1, 3], "DUPLICATE", [2], [1]),
    ("无序号", [0, 0, 0], "NO_NUMBERED", [], []),
    ("空", [], "NO_NUMBERED", [], []),
    ("含 0 但编号连续（0 不参与）", [0, 1, 2, 3, 0], "PASS", [], []),
    ("单个 1", [1], "PASS", [], []),
    ("乱序输入仍按集合判", [3, 1, 2], "PASS", [], []),
]

ok = 0
for name, ords, exp_v, exp_missing, exp_dupes in CASES:
    r = ordinal_verdict(hs(ords))
    good = (r["ordinal_verdict"] == exp_v
            and r["ordinal_missing"] == exp_missing
            and r["ordinal_duplicates"] == exp_dupes
            and r["ordinal_valid"] == (exp_v == "PASS"))
    ok += good
    print(f"{'OK ' if good else 'BAD'} {name:<28} -> {r['ordinal_verdict']:<12} "
          f"missing={r['ordinal_missing']} dupes={r['ordinal_duplicates']}")

print(f"\n{ok}/{len(CASES)} 通过")
raise SystemExit(0 if ok == len(CASES) else 1)
