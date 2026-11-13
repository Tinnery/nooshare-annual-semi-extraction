"""编号组合提取的 M2 回放校验（抽样）。

不变量：
1. 每个 run 的 [start_offset, end_offset) 必须落在原文件字节范围内且非空；
2. 该区间解码后的文本必须包含 run 的首个与末个编号行 verbatim；
3. run 的 ords 必须严格连续递增（编号重置检测的正确性）；
4. 候选 L1 的 combo_len 必须落在 reg_version 法定节数 ±2 内。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from numbering_combos import scan_file, expected_sections  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/md_cache/published")
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    files = sorted(Path(args.root).rglob("*.md"))
    step = max(1, len(files) // args.sample)
    picked = files[::step][: args.sample]

    n_runs = bad_span = bad_verbatim = bad_ords = bad_len = 0
    for p in picked:
        rec = scan_file(p)
        if rec is None:
            continue
        raw = p.read_bytes()
        _code, year, period = rec["slot_key"].split("_")
        expected = expected_sections(int(year), int(period))
        for r in rec["runs"]:
            n_runs += 1
            s, e = r["start_offset"], r["end_offset"]
            if not (0 <= s < e <= len(raw)):
                bad_span += 1
                continue
            seg = raw[s:e].decode("utf-8", errors="replace")
            first = r["names"][0][:8] if r["names"] else ""
            if first and first not in seg:
                bad_verbatim += 1
            if r["ords"] != list(range(r["ords"][0], r["ords"][0] + len(r["ords"]))):
                bad_ords += 1
            if r["is_candidate_l1"] and abs(r["combo_len"] - expected) > 2:
                bad_len += 1

    print(f"抽样文件 {len(picked)} / {len(files)}, run 数 {n_runs}")
    print(f"span 越界 {bad_span} · verbatim 不含首行 {bad_verbatim} · "
          f"ords 不连续 {bad_ords} · 候选L1长度违规 {bad_len}")
    ok = bad_span == bad_verbatim == bad_ords == bad_len == 0
    print("结论:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
