"""Layer-0 一级标题候选语料构建（无判据、可回放）。

设计原则：
- 不预设"什么是一级标题"：只记录所有 H1/H2/H3 行与所有"第X章/节"出现处，
  由后续频次分析反推 codebook。
- verbatim 可回放：offset 是 byte offset（非 char offset），保证
  md_bytes[start:end].decode('utf-8') == verbatim 可直接验证（M2）。
- 零新增依赖：仅标准库；上游 canonical 签名只作只读旁证，缺席时跳过。
- 全量产出是「候选生成」，不是「合规判定」。

输出：JSONL，每行一份报告。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

# 上游只读旁证
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")
try:
    from annual_semi.identify._funcs.heading_verify import extract_heading_signature
    from annual_semi.semantic._funcs.report_structure import is_toc, is_heading
    _UPSTREAM_AVAILABLE = True
except ImportError:
    _UPSTREAM_AVAILABLE = False

RE_H = re.compile(r"^(#{1,6})\s+(.*)$")
RE_NUMBERED = re.compile(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])\s*(.*)")
RE_CROSSREF = re.compile(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节])")

CN_DIGIT = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "壹": 1, "贰": 2, "叁": 3,
    "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
}


def cn_to_int(s: str) -> int | None:
    """中文数字 → int（支持 十/十一/二十 等）。"""
    if s.isdigit():
        return int(s)
    if not s:
        return None
    if "十" in s:
        parts = s.split("十")
        left = CN_DIGIT.get(parts[0], 1) if parts[0] else 1
        right = CN_DIGIT.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return left * 10 + right
    if "百" in s:
        parts = s.split("百")
        left = CN_DIGIT.get(parts[0], 1) if parts[0] else 1
        rest = parts[1] if len(parts) > 1 else ""
        return left * 100 + (cn_to_int(rest) or 0 if rest else 0)
    val = 0
    for ch in s:
        if ch not in CN_DIGIT:
            return None
        val = val * 10 + CN_DIGIT[ch]
    return val


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def slot_key_from_path(p: Path) -> str | None:
    """published/<code>/<code>_<year>_<period>.md -> slot_key。"""
    m = re.match(r"^(\d{6})_(\d{4})_([24])\.md$", p.name)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}_{m.group(3)}"


def extract_one(path: Path) -> dict | None:
    """抽取单份报告的 Layer-0 语料。"""
    slot = slot_key_from_path(path)
    if slot is None:
        return None
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    h_lines: list[dict] = []
    numbered: list[dict] = []
    crossrefs: list[dict] = []

    offset = 0
    for lineno, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        start = offset
        end = offset + len(raw_line)
        offset = end
        line_text = raw_line.decode("utf-8", errors="replace")
        verbatim = line_text
        body = line_text.rstrip("\r\n")

        m = RE_H.match(body)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            h_lines.append({
                "line": lineno,
                "start": start,
                "end": end,
                "verbatim": verbatim,
                "level": level,
                "text": title,
                "is_toc_line": is_toc(title) if _UPSTREAM_AVAILABLE else None,
                "is_heading": is_heading(title) if _UPSTREAM_AVAILABLE else None,
            })
            nm = RE_NUMBERED.search(title)
            if nm and level == 1:
                numbered.append({
                    "line": lineno,
                    "start": start,
                    "end": end,
                    "verbatim": verbatim,
                    "marker": f"第{nm.group(1)}{nm.group(2)}",
                    "marker_type": nm.group(2),
                    "ordinal_cn": nm.group(1),
                    "ordinal": cn_to_int(nm.group(1)),
                    "name": nm.group(3).strip(),
                })
        elif RE_CROSSREF.search(body):
            for cm in RE_CROSSREF.finditer(body):
                crossrefs.append({
                    "line": lineno,
                    "marker": f"第{cm.group(1)}{cm.group(2)}",
                    "context": body[:120],
                })
                break

    h1 = [h for h in h_lines if h["level"] == 1]
    combo_raw = "|".join(h["text"] for h in h1)
    combo_numbered = "|".join(
        f"{n['marker']}:{n['name']}" for n in numbered
    )
    canonical = extract_heading_signature(text) if _UPSTREAM_AVAILABLE else []

    def fp(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    return {
        "slot_key": slot,
        "path": str(path),
        "source_sha256": sha256_bytes(raw),
        "n_bytes": len(raw),
        "n_lines": lineno,
        "n_h1": len(h1),
        "n_h2": sum(1 for h in h_lines if h["level"] == 2),
        "n_h3": sum(1 for h in h_lines if h["level"] == 3),
        "h1": h1,
        "numbered": numbered,
        "n_crossref": len(crossrefs),
        "crossref_sample": crossrefs[:3],
        "canonical_signature": canonical,
        "canonical_combo": "|".join(canonical),
        "combo_raw": combo_raw,
        "combo_numbered": combo_numbered,
        "fp_h1": fp(combo_raw),
        "fp_numbered": fp(combo_numbered),
        "fp_canonical": fp("|".join(canonical)),
    }
