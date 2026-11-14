"""编号组合与法定节数查询。

提供 expected_sections() 查询指定年份/期别的法定节数，
以及编号解析工具。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .corpus import cn_to_int

# 编号体系
PATTERNS = [
    ("CH_ZH",    re.compile(r"^第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])\s*[:：\.．]?\s*(\D.*)$")),
    ("CN_DUN",   re.compile(r"^([一二三四五六七八九十]{1,3})\s*[、\.．]\s*(\D.*)$")),
    ("AR_DOT",   re.compile(r"^(\d{1,2})\s*[\.．、]\s*(\D.*)$")),
    ("AR_PAREN", re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*(\D.*)$")),
    ("PAREN_CN", re.compile(r"^[（(]\s*([一二三四五六七八九十]{1,3})\s*[）)]\s*(\D.*)$")),
]
RE_MULTILEVEL = re.compile(r"^\d{1,2}\.\d{1,2}")
FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")

# 法定节数（来自 legal_chapters.json）
_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"
_LC_PATH = _SPEC_DIR / "legal_chapters.json"
if _LC_PATH.exists():
    SECTION_COUNTS = {
        k: len(v["sections"])
        for k, v in json.loads(_LC_PATH.read_text(encoding="utf-8"))["chapters"].items()
    }
else:
    SECTION_COUNTS = {}


def expected_sections(year: int, period: int) -> int:
    """by_period_end 裁决：2021-2024 适用〔2021〕15号/16号，2025+ 适用〔2025〕3号/4号。"""
    if year <= 2024:
        key = "no2_2021_15" if period == 4 else "no3_2021_16"
    else:
        key = "no2_2025_3" if period == 4 else "no3_2025_4"
    return SECTION_COUNTS.get(key, 10)


def parse_numbered_line(body: str) -> dict | None:
    """返回 {system, ordinal, name, kind}；非编号行返回 None。"""
    if RE_MULTILEVEL.match(body):
        return None
    s = body.translate(FULLWIDTH).strip()
    for system, pat in PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        raw_num = m.group(1)
        ordinal = cn_to_int(raw_num)
        if ordinal is None or ordinal < 1 or ordinal > 60:
            return None
        if system == "CH_ZH":
            name = m.group(3).strip()
            kind = m.group(2)
        else:
            name = m.group(2).strip()
            kind = system
        return {"system": system, "ordinal": ordinal, "name": name, "kind": kind}
    return None
