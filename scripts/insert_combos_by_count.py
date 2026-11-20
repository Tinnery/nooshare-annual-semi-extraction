"""把 h1_combo_raw.json 中 count >= 阈值的组合写入 PG 标准库。

用法（在 pro 主机、repo 根目录、PYTHONPATH=. 下运行）：
    uv run python scripts/insert_combos_by_count.py --dry-run
    uv run python scripts/insert_combos_by_count.py

要点：
- hash 必须与 pattern_matcher._pattern_hash / _normalize_pattern 完全一致，
  否则精确匹配（策略1）永远失效。
- 幂等：ON CONFLICT (pattern_hash) DO NOTHING + pattern 全文去重。
- 可选 --fix-existing-hash：把旧算法写入的 hash 幂等修正为 matcher 算法。
- headings 只保留识别/纠错所需字段，与库内已有记录结构一致。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2

PG = dict(host="pg.pro.neuralj.com", port=5432, dbname="nooshare_dev",
          user="travis", password="sheeta-pg")

# 与 pattern_matcher 使用同一算法，避免历史上出现过的 hash 不一致
from annual_semi_extraction.h1.pattern_matcher import (  # noqa: E402
    _normalize_pattern,
    _pattern_hash,
)


def phash_of(pattern: list[str]) -> str:
    return _pattern_hash(_normalize_pattern(list(pattern)))


def slim_headings(headings: list[dict]) -> list[dict]:
    return [
        {
            "ordinal": h.get("ordinal"),
            "raw_name": h.get("raw_name", ""),
            "canonical_name": h.get("canonical_name", ""),
        }
        for h in headings
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/h1_combo_raw.json")
    ap.add_argument("--threshold", type=int, default=816)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fix-existing-hash", action="store_true",
                    help="把库内旧算法 hash 幂等修正为 matcher 算法")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"错误：输入文件不存在 {src}", file=sys.stderr)
        return 2
    data = json.loads(src.read_text(encoding="utf-8"))
    candidates = [c for c in data["combos"] if c["count"] >= args.threshold]
    candidates.sort(key=lambda c: -c["count"])
    print(f"输入: {src} | 总组合 {len(data['combos'])} | "
          f"count>={args.threshold}: {len(candidates)}")

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT id, pattern_hash, pattern, count "
                "FROM annual_semi.h1_pattern_library ORDER BY id")
    existing = cur.fetchall()
    by_pattern = {tuple(p): (i, h, c) for i, h, p, c in existing}
    hashes = {h for _, h, _, _ in existing}
    print(f"PG 现有: {len(existing)} 条")

    # 计划 A：新增
    inserts: list[tuple[str, list[str], int, list[dict], int]] = []
    for c in candidates:
        pat = list(c["pattern"])
        h = phash_of(pat)
        if tuple(pat) in by_pattern:
            print(f"  跳过(已有同 pattern) count={c['count']} id={by_pattern[tuple(pat)][0]}")
            continue
        if h in hashes:
            print(f"  跳过(hash 冲突) count={c['count']} hash={h[:12]}")
            continue
        inserts.append((h, pat, c["count"], slim_headings(c["headings"]), c["n_headings"]))
        hashes.add(h)

    # 计划 B：修正旧 hash
    updates: list[tuple[int, str, str]] = []
    if args.fix_existing_hash:
        for i, old_h, p, _cnt in existing:
            new_h = phash_of(list(p))
            if new_h != old_h:
                updates.append((i, old_h, new_h))

    print(f"\n计划：新增 {len(inserts)} 条 | 修正 hash {len(updates)} 条")
    for h, pat, cnt, _hd, n in inserts:
        print(f"  INSERT count={cnt:<6} n={n:<3} hash={h[:12]} p0={pat[0][:24]!r}")
    for i, o, n in updates:
        print(f"  UPDATE id={i} hash {o[:12]} -> {n[:12]}")

    if args.dry_run:
        print("\n[DRY-RUN] 未写入，回滚")
        cur.close()
        conn.rollback()
        conn.close()
        return 0

    try:
        # 先修 hash（避免与待插入 hash 冲突），再插入
        for i, _old, new_h in updates:
            cur.execute(
                "UPDATE annual_semi.h1_pattern_library SET pattern_hash=%s WHERE id=%s",
                (new_h, i),
            )
        for h, pat, cnt, hd, _n in inserts:
            cur.execute(
                """INSERT INTO annual_semi.h1_pattern_library
                       (pattern_hash, pattern, count, headings)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (pattern_hash) DO NOTHING
                   RETURNING id""",
                (h, pat, cnt, json.dumps(hd, ensure_ascii=False)),
            )
            row = cur.fetchone()
            print(f"  -> {'新增 id=' + str(row[0]) if row else '已存在跳过'} "
                  f"count={cnt} hash={h[:12]}")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"写入失败，已回滚: {type(e).__name__}: {e}", file=sys.stderr)
        cur.close()
        conn.close()
        return 1

    # 验证
    cur.execute("SELECT id, pattern_hash, count, jsonb_array_length(headings) "
                "FROM annual_semi.h1_pattern_library ORDER BY count DESC")
    rows = cur.fetchall()
    print(f"\n验证：表内共 {len(rows)} 条")
    for i, h, cnt, nh in rows:
        print(f"  id={i:<3} count={cnt:<6} n_headings={nh:<3} hash={h[:12]}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
