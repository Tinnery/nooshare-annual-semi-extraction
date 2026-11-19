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

_VERSIONS_PATH = _SPEC_DIR / "regulatory_versions.json"
_REGULATORY_VERSIONS = json.loads(_VERSIONS_PATH.read_text(encoding="utf-8"))


def expected_sections(year: int, period: int) -> int | None:
    """按 regulatory_versions.json 的生效日和报告期末返回法定节数。

    未登记该期间适用版本时返回 None；调用方应标记为版本未解析，
    不得将其解释为“不适用”或默认套用其他年份模板。
    """
    if period == 4:
        period_end = f"{year:04d}-12-31"
    elif period == 2:
        period_end = f"{year:04d}-06-30"
    else:
        raise ValueError(f"period 必须是 2 或 4，实际: {period}")

    candidates = [
        version
        for version in _REGULATORY_VERSIONS["versions"]
        if int(version["applies_to_period"]) == period
        and version["effective_from"] <= period_end
        and version.get("chapter_set_key") in SECTION_COUNTS
    ]
    if not candidates:
        return None
    selected = max(candidates, key=lambda version: version["effective_from"])
    return SECTION_COUNTS[selected["chapter_set_key"]]
