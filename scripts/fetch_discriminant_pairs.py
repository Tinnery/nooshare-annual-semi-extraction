"""构造并实测「降级链判别对」。

数据来源（全部在 01 §四授权边界内）：
- `annual_semi.reconciled_report` 的 `selection_rule IN (backup_l1,l2,l3)` 槽位
- 其 `verify_result` 中同 slot 的 `status='fail'` 的 published MD（被淘汰侧）
- 该槽位的 `winner_md_path`（降级胜者侧）
两者是**同一份报告的两个转换结果，只差转换链路**，且 fail 侧自带结构异常先验。

这是比「跨公司比较」强得多的判别对，且不需要源 HTML / PDF。

输出：data/discriminant_pairs.json
"""

from __future__ import annotations

import json
import sys
import urllib3
from collections import Counter
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, r"C:\dev\nooshare-annual-semi")
sys.path.insert(0, str(Path(__file__).parent))

from heading_corpus import extract_one  # noqa: E402

ENDPOINT_URL = "https://s3.rustfs.pro.neuralj.com"
ACCESS_KEY = "charlie"
SECRET_KEY = "sheeta-rustfs"
BUCKET = "annual-semi"
CACHE = Path("data/md_cache/pairs")
THRESHOLD = 0.3  # 上游 D-3 冻结


def db_pairs() -> list[dict]:
    from annual_semi.db._conn import connect
    c = connect()
    cur = c.cursor()
    cur.execute("""
        SELECT r.stock_code, r.report_year, r.period,
               r.winner_md_path, r.selection_rule, r.candidate_count,
               v.status, v.md_path, v.reason, v.md_size
        FROM annual_semi.reconciled_report r
        JOIN annual_semi.verify_result v
          ON v.stock_code = r.stock_code
         AND v.native_id = r.stock_code || '_' || r.report_year || '_' || r.period
        WHERE r.period IN (2,4) AND r.report_year BETWEEN 2021 AND 2024
          AND r.selection_rule IN ('backup_l1','backup_l2','backup_l3')
          AND v.status = 'fail'
        ORDER BY r.stock_code, r.report_year, r.period
    """)
    out = []
    for x in cur.fetchall():
        out.append({
            "slot_key": f"{x[0]}_{x[1]}_{x[2]}",
            "winner_md_path": x[3], "selection_rule": x[4],
            "candidate_count": x[5], "fail_md_path": x[7],
            "fail_reason": x[8], "fail_md_size": x[9],
        })
    c.close()
    return out


def make_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY,
        verify=False, config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def fetch(client, key: str, dest: Path) -> str:
    """下载到规范文件名，保证 extract_one 能解析 slot_key。返回状态。"""
    if dest.exists():
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(BUCKET, key, str(dest))
        return "downloaded"
    except Exception as e:
        return f"error:{type(e).__name__}:{e}"


def jaccard(a: set, b: set) -> float:
    u = a | b
    return 0.0 if not u else len(a ^ b) / len(u)


def main() -> None:
    pairs = db_pairs()
    print(f"降级链判别对: {len(pairs)} 组", flush=True)
    client = make_client()

    results = []
    for i, p in enumerate(pairs, start=1):
        slot = p["slot_key"]
        fail_path = CACHE / "fail" / f"{slot}.md"
        win_path = CACHE / "winner" / f"{slot}.md"
        s1 = fetch(client, p["fail_md_path"], fail_path)
        s2 = fetch(client, p["winner_md_path"], win_path)
        if i % 10 == 0:
            print(f"  {i}/{len(pairs)} ...", flush=True)

        if not fail_path.exists() or not win_path.exists():
            results.append({**p, "error": f"fetch fail={s1} winner={s2}"})
            continue

        try:
            a = extract_one(fail_path)
            b = extract_one(win_path)
            if a is None or b is None:
                results.append({**p, "error": "extract_one returned None"})
                continue
            sa, sb = set(a["canonical_signature"]), set(b["canonical_signature"])
            d = jaccard(sa, sb)
            results.append({
                **p,
                "fail_sha256": a["source_sha256"], "winner_sha256": b["source_sha256"],
                "fail_n_h1": a["n_h1"], "winner_n_h1": b["n_h1"],
                "fail_n_numbered": len(a["numbered"]),
                "winner_n_numbered": len(b["numbered"]),
                "fail_sig": a["canonical_signature"],
                "winner_sig": b["canonical_signature"],
                "jaccard_distance": round(d, 3),
                "verdict": "DIVERGENT" if d > THRESHOLD else "CONSISTENT",
                "only_in_fail": sorted(sa - sb),
                "only_in_winner": sorted(sb - sa),
            })
        except Exception as e:
            results.append({**p, "error": f"{type(e).__name__}: {e}"})

    ok = [r for r in results if "jaccard_distance" in r]
    summary = {
        "n_pairs": len(pairs),
        "n_resolved": len(ok),
        "n_errors": len(results) - len(ok),
        "threshold": THRESHOLD,
        "n_divergent": sum(1 for r in ok if r["verdict"] == "DIVERGENT"),
        "verdict_counts": dict(Counter(r["verdict"] for r in ok)),
        "h1_delta_distribution": dict(Counter(r["winner_n_h1"] - r["fail_n_h1"] for r in ok)),
        "numbered_delta_distribution": dict(
            Counter(r["winner_n_numbered"] - r["fail_n_numbered"] for r in ok)
        ),
        "pairs": results,
    }
    Path("data/discriminant_pairs.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成: 解析 {len(ok)}/{len(pairs)} 组, 分歧 {summary['n_divergent']} 组")
    print(f"H1 数差异分布: {summary['h1_delta_distribution']}")
    print(f"编号标题数差异分布: {summary['numbered_delta_distribution']}")
    print("-> data/discriminant_pairs.json")


if __name__ == "__main__":
    main()
