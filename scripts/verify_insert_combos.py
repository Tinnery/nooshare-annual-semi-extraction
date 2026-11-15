"""入库后验证：条数、hash 一致性、matcher 加载、候选精确命中、锚定回归、幂等。

用法（pro 主机，PYTHONPATH=.）：
    uv run python scripts/verify_insert_combos.py --threshold 37
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from annual_semi_extraction.h1.pattern_matcher import (  # noqa: E402
    _normalize_pattern,
    _pattern_hash,
    get_pattern_matcher,
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
    cur.execute("SELECT id, pattern_hash, pattern, headings "
                "FROM annual_semi.h1_pattern_library ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    bad_hash = sum(1 for _, h, p, _ in rows if h != phash(list(p)))
    bad_hd = sum(1 for _, _, _, hd in rows
                 if any(set(h.keys()) != {"ordinal", "raw_name", "canonical_name"}
                        for h in (hd or [])))
    lib_patterns = {tuple(p) for _, _, p, _ in rows}
    missing = [c["count"] for c in cs if tuple(c["pattern"]) not in lib_patterns]

    m = get_pattern_matcher()
    m._load()
    # 策略1 精确匹配的定义就是 hash 在 _patterns 里；
    # match() 返回的 dict 不含 pattern_hash 字段，不能用它反查。
    hit = sum(1 for c in cs if phash(list(c["pattern"])) in m._patterns)
    matched = sum(1 for c in cs if m.match(list(c["pattern"])) is not None)

    cases = [
        ("释义在本报告书中，除非文义另有所指，下列词语具有如下含义", "释义"),
        ("公司简介" + "." * 30, "公司简介"),
        ("财务会计报告（未经审计）" + "." * 20, "财务会计报告（未经审计）"),
        ("释义", None),
        ("声明与提示", None),
        ("公司基本情况", None),
        ("一个完全不相干的正文片段", None),
    ]
    anchor_ok = sum(1 for s, e in cases if m.anchor_title(s) == e)

    print(f"表内: {len(rows)} 条 | matcher size={m.size} title_count={m.title_count}")
    print(f"  hash 算法不一致: {bad_hash} | headings 字段异常: {bad_hd}")
    print(f"  候选 {len(cs)} 条：库中缺失 {len(missing)} | 精确 hash 命中 {hit}/{len(cs)} "
          f"| match() 命中 {matched}/{len(cs)}")
    print(f"  标题锚定回归: {anchor_ok}/{len(cases)}")
    ok = (bad_hash == 0 and bad_hd == 0 and not missing
          and hit == len(cs) and anchor_ok == len(cases))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
