"""法定节数查询。

提供 expected_sections()：指定年份/期别的法定节数（来自 legal_chapters.json）。
编号解析逻辑统一在 extractor.py（含 marker/name 截断的增强版）。
"""

from __future__ import annotations

import json
from pathlib import Path

# 法定节数（来自 legal_chapters.json）
_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec" / "specs"
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
