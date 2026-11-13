"""一级标题观测值的形态分类与确定性切分（不清洗、不覆盖 verbatim）。

目的不是"提高一级标题识别率"（10 已论证本 repo 不需要该能力），而是：
  1. 把 MD 转换链路造成的**系统性损伤**显式建模，使其不污染统计分母；
  2. 给 EXTRACTION_FAILURE 提供可诊断的分层（10 §六保留的最小能力之一）；
  3. 给「字数」列 / semantic_path 提供可回指的边界（之另一）。

铁律：
- verbatim 原样保留；所有修正都是**派生字段**，且每个 segment 带可回放的相对 offset。
- 合法名称只来自外部有限集：`legal_chapters.json` 全部版本节名 + 上游
  `report_patterns.json` canonical 变体。**禁止手敲关键词表**（R'1②⑥）。
- 不做"AGENT 判断正确性"；只做由物理形态 + 有限集驱动的确定性切分。

形态优先级（首个命中即定）：
  TOC_ROW      一行含 >=2 个 第X章/节 marker，或含 Word 域错误文本
  TOC_TAIL     点线残留 / 页码尾巴
  CHECKBOX     conditional 章节的适用性表单残留
  GLUED_BODY   标题与正文首段粘连
  EMPTY_NAME   marker 后无名称
  NONSTRUCTURAL 公司名 / 年份报告名 / 审计报告 / 财报附注
  CLEAN        命中合法名称集
  UNRESOLVED   其余（不进统计分母，M2）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(r"C:\dev\nooshare-annual-semi")

RE_MARKER = re.compile(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])")
RE_DOTLEADER = re.compile(r"[\.…·]{2,}")
RE_WORDERR = re.compile(r"错误！未定义书签|错误!未定义书签")
RE_CHECKBOX = re.compile(r"[□■☑☐\?？]\s*适用|适用\s*[□■☑☐\?？]|□\s*不适用")
RE_SENT_END = re.compile(r"[。！？；]")
RE_COMPANY = re.compile(r"(股份有限公司|有限公司|集团股份|银行股份|证券股份)")
RE_YEAR_REPORT = re.compile(r"^\d{4}\s*年(半)?年度报告")
RE_ATTACHMENT = re.compile(r"^(审计报告|审阅报告|财务报表附注|审计报告及财务报表)")
ATTACHMENT_KEYWORDS = ("主要项目注释", "合并财务报表项目注释", "财务报表项目注释")
# 扉页「目录」的空白变体 / 财报附注续行 / 纯 marker（名称在下一行）
RE_TOC_TITLE = re.compile(r"^\s*目\s*录\s*$")
RE_ATTACHMENT_CONT = re.compile(r"^[一二三四五六七八九十]+[、\.]\s*.{0,30}\(?（?续|^\s*项目列示\s*$")
RE_PURE_MARKER = re.compile(r"^\s*第\s*[一二三四五六七八九十百零〇0-9]+\s*[章节部分篇]\s*$")


def legal_name_set() -> list[str]:
    """外部有限集：法规节名 + 上游 canonical 变体。按长度降序供最长前缀匹配。"""
    names: set[str] = set()
    lc = json.loads(
        (ROOT / "annual_semi_extraction/spec/legal_chapters.json").read_text(encoding="utf-8")
    )
    for _key, info in lc["chapters"].items():
        for s in info["sections"]:
            names.add(s["name"].strip())
    rp = UPSTREAM / "reference/report_patterns.json"
    if rp.exists():
        rp_data = json.loads(rp.read_text(encoding="utf-8"))
        for variants in rp_data.get("canonical", {}).values():
            for v in variants:
                names.add(v.strip())
    # 法规与实报的连写变体（"第一节重要提示" 无空格）由前缀匹配自然覆盖
    return sorted((n for n in names if n), key=len, reverse=True)


LEGAL_NAMES = legal_name_set()
# 预编译单一交替正则，避免 O(n×m) 逐变体扫描（沿用上游 heading_verify 的做法）
RE_LEGAL = re.compile("|".join(re.escape(n) for n in LEGAL_NAMES))


def _strip_noise(s: str) -> tuple[str, list[str]]:
    """剥离转换残留，返回 (干净文本, 命中的噪声标签)。可重复施加，直到稳定。"""
    tags: list[str] = []
    prev = None
    while prev != s:
        prev = s
        if RE_WORDERR.search(s):
            s = RE_WORDERR.split(s)[0]
            tags.append("word_field_error")
        m = RE_DOTLEADER.search(s)
        if m:
            s = s[: m.start()]
            tags.append("dot_leader")
        if RE_CHECKBOX.search(s):
            s = RE_CHECKBOX.sub("", s)
            tags.append("checkbox")
        # 目录页码：尾部纯数字（前面有点线/空白）
        s = re.sub(r"[\s\.…·]*\d{1,4}\s*$", "", s)
        # 全角/半角空白折叠
        s = re.sub(r"[\u3000\s]+", " ", s).strip()
    return s, tags


def split_markers(text: str) -> list[tuple[int, int, str]]:
    """按行内所有 第X章/节 marker 切成片段 -> [(start, end, fragment)]。"""
    marks = list(RE_MARKER.finditer(text))
    if not marks:
        return [(0, len(text), text)]
    out = []
    for i, m in enumerate(marks):
        s = m.start()
        e = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((s, e, text[s:e]))
    # marker 之前若有内容（如年份前缀），并入第一段
    if marks[0].start() > 0 and out:
        lead = text[: marks[0].start()]
        if lead.strip():
            out[0] = (0, out[0][1], lead + out[0][2])
    return out


def classify_h1(text: str) -> dict:
    """对单个 H1 文本做形态分类与切分。text 不含 '# ' 前缀与换行。"""
    markers = list(RE_MARKER.finditer(text))
    if len(markers) >= 2 or RE_WORDERR.search(text):
        morph = "TOC_ROW"
    elif RE_DOTLEADER.search(text):
        morph = "TOC_TAIL"
    elif RE_CHECKBOX.search(text):
        morph = "CHECKBOX"
    elif RE_PURE_MARKER.match(text):
        morph = "EMPTY_NAME"  # 名称在下一行，不在本行
    elif (RE_TOC_TITLE.match(text) or RE_YEAR_REPORT.match(text)
          or RE_ATTACHMENT.match(text) or RE_ATTACHMENT_CONT.match(text)
          or any(k in text for k in ATTACHMENT_KEYWORDS)
          or (RE_COMPANY.search(text) and not markers)):
        morph = "NONSTRUCTURAL"
    else:
        morph = None  # 待切分后按结果判定

    segments = []
    for s, e, frag in split_markers(text):
        clean, noise_tags = _strip_noise(frag)
        m = RE_LEGAL.search(clean)
        if m and m.start() == 0:
            name = m.group(0)
            suffix = clean[m.end():].strip()
            glued = bool(suffix and RE_SENT_END.search(suffix))
            segments.append({
                "start": s, "end": e,
                "name": name,
                "name_end": s + m.end(),
                "body_suffix": suffix if glued else "",
                "glued": glued,
                "noise_tags": noise_tags,
                "resolvable": True,
            })
        elif m:
            # 合法名出现在中间。若前缀只是 marker 本身，属正常形态，不打噪声标签。
            name = m.group(0)
            prefix = clean[: m.start()].strip()
            just_marker = bool(
                re.fullmatch(r"第\s*[一二三四五六七八九十百零〇0-9]+\s*[章节部分篇]\s*[:：\.．]?", prefix)
            )
            tags = noise_tags + ([] if just_marker else ["prefix_stripped"])
            segments.append({
                "start": s, "end": e, "name": name,
                "name_end": s + m.end(),
                "body_suffix": clean[m.end():].strip(),
                "glued": bool(RE_SENT_END.search(clean[m.end():])),
                "noise_tags": tags,
                "resolvable": True,
            })
        else:
            segments.append({
                "start": s, "end": e, "name": "",
                "name_end": s,
                "body_suffix": clean,
                "glued": False,
                "noise_tags": noise_tags + ["no_legal_name"],
                "resolvable": False,
            })

    if morph is None:
        if not segments:
            morph = "EMPTY_NAME"
        elif all(sg["glued"] for sg in segments):
            morph = "GLUED_BODY"
        elif not any(sg["resolvable"] for sg in segments):
            morph = "UNRESOLVED"
        elif all(not sg["name"] for sg in segments):
            morph = "EMPTY_NAME"
        else:
            morph = "CLEAN"

    return {
        "morphology": morph,
        "n_markers": len(markers),
        "n_segments": len(segments),
        "segments": segments,
        "clean_names": [sg["name"] for sg in segments if sg["name"]],
    }


def main() -> None:
    """自检：打印合法名称集规模与几个已知误识别样本的修正结果。"""
    print(f"合法名称集: {len(LEGAL_NAMES)} 条（法规节名 + 上游 canonical 变体）")
    samples = [
        "第一节 重要提示、目录和释义公司董事会、监事会及董事、监事、高级管理人员保证半年度报告内容的真实、准确、完整，不存在虚假记载、误导性陈述或重大遗漏，并承担个别和连带的法律责任。",
        "第五节环境和社会责任 ...... 24第六节重要事项..............................................................................................................................",
        "第九节 债券相关情况?适用 □不适用",
        "第一节 重要提示、目录和释义 ...... 错误！未定义书签。第二节 公司简介和主要财务指标 ...... 错误！未定义书签。",
        "第十节 财务报告",
    ]
    for s in samples:
        r = classify_h1(s)
        print(f"\n{morph_str(r)} <- {s[:70]}")
        for sg in r["segments"][:4]:
            print(f"   name={sg['name']!r} glued={sg['glued']} tags={sg['noise_tags']}")


def morph_str(r: dict) -> str:
    return f"[{r['morphology']}] markers={r['n_markers']} segs={r['n_segments']} names={r['clean_names'][:4]}"


if __name__ == "__main__":
    main()
