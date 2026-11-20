"""入库前置检查：hash 算法一致性、pattern/hash 冲突、候选序号合规。

用法（pro 主机，PYTHONPATH=.）：
    uv run python scripts/precheck_insert_combos.py --threshold 37
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from annual_semi_extraction.h1.pattern_matcher import (  # noqa: E402
    _normalize_pattern,
    _pattern_hash,
)

PG = dict(host="pg.pro.neuralj.com", port=5432, dbname="nooshare_dev",
          user="travis", password="sheeta-pg")


def phash(pattern: list[str]) -> str:
    return _pattern_hash(_normalize_pattern(list(pattern)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/h1_combo_raw.json")
    ap.add_argument("--threshold", type=int, required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    cs = [c for c in data["combos"] if c["count"] >= args.threshold]

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT id, pattern_hash, pattern "
                "FROM annual_semi.h1_pattern_library ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    old_hashes = {h for _, h, _ in rows}
    old_patterns = {tuple(p) for _, _, p in rows}
    new = [(c["count"], phash(list(c["pattern"])), tuple(c["pattern"]),
            c.get("ordinal_valid"), c.get("n_headings"), c["pattern"][0])
           for c in cs]

    checks = {
        "库内 hash 算法不一致": sum(1 for _, h, p in rows if h != phash(list(p))),
        "待插入与库内 hash 交集": len({h for _, h, _, _, _, _ in new} & old_hashes),
        "待插入与库内 pattern 重复": len({p for _, _, p, _, _, _ in new} & old_patterns),
        "待插入 hash 内部重复": len(new) - len({h for _, h, _, _, _, _ in new}),
        "ordinal_valid 非 true": sum(1 for _, _, _, v, _, _ in new if v is not True),
    }
    print(f"PG 现有 {len(rows)} 条 | 候选 count>={args.threshold}: {len(cs)} 条")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print(f"  count 范围: {min(c['count'] for c in cs)} ~ {max(c['count'] for c in cs)}")
    for cnt, h, _p, _v, n, p0 in new:
        if cnt == args.threshold:
            print(f"  阈值边界: count={cnt} n={n} p0={p0!r} hash={h[:12]}")

    ok = all(v == 0 for v in checks.values())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
