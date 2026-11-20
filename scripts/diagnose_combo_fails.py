"""诊断 rustfs-combo 的 fail 是抽取本身失败，还是并行引入的异常。"""
import os
import traceback
from collections import Counter
from pathlib import Path
import tempfile

os.environ["RUSTFS_ENDPOINT"] = "http://127.0.0.1:9000"

from annual_semi_extraction.rustfs import get_client  # noqa: E402
from annual_semi_extraction.h1.extractor import extract  # noqa: E402
from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher  # noqa: E402

c = get_client()
matcher = get_pattern_matcher()
objs = [o for o in c.list_objects(prefix="published/") if o["key"].endswith(".md")][:300]
tmp = Path(tempfile.mkdtemp())

reasons = Counter()
samples = {}
for o in objs:
    key = o["key"]
    p = tmp / key.rsplit("/", 1)[-1]
    try:
        p.write_text(c.read_text(key), encoding="utf-8")
        rec = extract(p)
        if rec is None:
            reasons["extract_returned_none"] += 1
            samples.setdefault("extract_returned_none", key)
            continue
        headings = rec.get("headings", [])
        if not headings:
            reasons["no_headings"] += 1
            samples.setdefault("no_headings", key)
            continue
        pat = tuple(h.get("raw_name", "") for h in headings if h.get("raw_name", ""))
        if not pat:
            reasons["empty_pattern"] += 1
            samples.setdefault("empty_pattern", key)
            continue
        if matcher.match(list(pat)):
            reasons["library_match"] += 1
            samples.setdefault("library_match", key)
        else:
            reasons["ok"] += 1
    except Exception as e:
        tag = f"exception:{type(e).__name__}"
        reasons[tag] += 1
        samples.setdefault(tag, f"{key} -> {e}")
    finally:
        p.unlink(missing_ok=True)

print("样本数:", len(objs))
for k, v in reasons.most_common():
    print(f"  {k:<28} {v:>4}  e.g. {samples.get(k, '')}")
