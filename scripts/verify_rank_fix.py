"""对照验证：库词表打分开关 0/1 下，跨层级误识别样本是否被修好。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["RUSTFS_ENDPOINT"] = "http://127.0.0.1:9000"
os.environ["H1_FROZEN_EMIT"] = "0"
import annual_semi_extraction.rustfs as _r
_r.ENDPOINT_URL = "http://127.0.0.1:9000"
_r._server_time_offset = None

import annual_semi_extraction.h1.extractor as ext
from annual_semi_extraction.rustfs import get_client

SLOTS = ["600010_2008_2", "600056_2008_2", "600063_2008_2",
         "600066_2008_2", "600067_2008_2"]
client = get_client()
tmp = Path(tempfile.mkdtemp(prefix="rank_fix_"))


def read(slot: str) -> str:
    code = slot.split("_")[0]
    key = f"published/{code}/{slot}.md"
    try:
        return client.read_text(key)
    except Exception:
        for o in client.list_objects(prefix="published/"):
            if Path(o["key"]).stem == slot:
                return client.read_text(o["key"])
    raise FileNotFoundError(slot)


def run(slot: str, enabled: bool):
    ext._LIBRARY_RANK_ENABLED = enabled
    p = tmp / f"{slot}.md"
    p.write_text(read(slot), encoding="utf-8")
    rec = ext.extract(p)
    p.unlink(missing_ok=True)
    return rec


def brief(rec):
    if rec is None or not rec.get("headings"):
        return "无 headings", []
    hs = rec["headings"]
    lines = [h.get("line") for h in hs]
    back = any(lines[i] > lines[i + 1] for i in range(len(lines) - 1)
               if lines[i] is not None and lines[i + 1] is not None)
    head = (f"{len(hs)} 标题 | {rec.get('ordinal_verdict')} | "
            f"line回跳={'是' if back else '否'} | lib={rec.get('library_match')}")
    rows = [(h.get("ordinal"), h.get("line"), h.get("raw_name")) for h in hs]
    return head, rows


fixed = 0
for slot in SLOTS:
    a = run(slot, False)
    b = run(slot, True)
    ha, ra = brief(a)
    hb, rb = brief(b)
    print(f"\n=== {slot} ===")
    print(f"  改前: {ha}")
    for o, l, n in ra:
        print(f"     {o:>2}  L{l:<5}  {n}")
    print(f"  改后: {hb}")
    for o, l, n in rb:
        print(f"     {o:>2}  L{l:<5}  {n}")
    bad_before = ra and ra[0][2] in ("有限售条件股份", "未上市流通股份")
    bad_after = rb and rb[0][2] in ("有限售条件股份", "未上市流通股份")
    ok = bad_before and not bad_after
    fixed += ok
    print(f"  -> {'修复 OK' if ok else ('本就不是该问题' if not bad_before else '未修复 FAIL')}")

print(f"\n修复 {fixed}/{len(SLOTS)} 份")
