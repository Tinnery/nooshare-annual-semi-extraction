"""在 pro 主机验证 RUSTFS_ENDPOINT=http://127.0.0.1:9000 能否签名读取。"""
import os
import time

os.environ["RUSTFS_ENDPOINT"] = "http://127.0.0.1:9000"

from annual_semi_extraction.rustfs import get_client  # noqa: E402

c = get_client()
print("endpoint:", c.endpoint)

t = time.perf_counter()
objs = c.list_objects(prefix="published/000001/")
print("list ok:", len(objs), "objects", round(time.perf_counter() - t, 3), "s")

k = objs[0]["key"]
t = time.perf_counter()
txt = c.read_text(k)
print("read ok:", k, len(txt), "chars", round((time.perf_counter() - t) * 1000, 1), "ms")

t = time.perf_counter()
for o in objs[:30]:
    c.read_text(o["key"])
dt = time.perf_counter() - t
print("serial 30:", round(dt, 3), "s", round(30 / dt, 1), "f/s")
