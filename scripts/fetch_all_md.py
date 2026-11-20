"""补齐 2021-2024 全部 winner MD 到本地缓存（纯下载，不做任何判定）。

全量提取是「候选生成」，不违反 01 §五.3（该条禁的是用全量当验证）。
复用单个 boto3 client，避免每文件重建连接（旧脚本 16 分钟只下 12k 的主因）。
"""

from __future__ import annotations

import sys
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from annual_semi.db._conn import connect  # noqa: E402

BUCKET = "annual-semi"
CACHE = Path("data/md_cache")


def main() -> None:
    c = connect()
    cur = c.cursor()
    cur.execute("""
        SELECT winner_md_path FROM annual_semi.reconciled_report
        WHERE period IN (2,4) AND report_year BETWEEN 2021 AND 2024
          AND winner_md_path IS NOT NULL
    """)
    keys = sorted({r[0] for r in cur.fetchall()})
    c.close()

    missing = [k for k in keys if not (CACHE / k).exists()]
    print(f"交付表路径 {len(keys)} 个，已缓存 {len(keys)-len(missing)}，待下载 {len(missing)}", flush=True)

    client = boto3.client(
        "s3", endpoint_url="https://s3.rustfs.pro.neuralj.com",
        aws_access_key_id="charlie", aws_secret_access_key="sheeta-rustfs",
        verify=False,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      max_pool_connections=32),
    )

    def one(key: str) -> tuple[str, str]:
        dest = CACHE / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.download_file(BUCKET, key, str(dest))
            return key, "ok"
        except Exception as e:
            return key, f"{type(e).__name__}"

    ok = 0
    errs: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {pool.submit(one, k): k for k in missing}
        for i, f in enumerate(as_completed(futs), start=1):
            _k, status = f.result()
            if status == "ok":
                ok += 1
            else:
                errs[status] = errs.get(status, 0) + 1
            if i % 2000 == 0:
                print(f"  {i}/{len(missing)} ok={ok} err={sum(errs.values())}", flush=True)

    print(f"完成: 新增 {ok}, 失败 {sum(errs.values())} {errs}", flush=True)
    total = sum(1 for _ in CACHE.rglob("*.md"))
    print(f"缓存 MD 总数: {total}", flush=True)


if __name__ == "__main__":
    main()
