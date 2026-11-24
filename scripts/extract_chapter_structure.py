"""从法规原文 PDF 提取法定章节集（E1 判定程序的直接输入）。

纯事实提取，不涉及 reg_version 自变量裁决。
输出：annual_semi_extraction/spec/chapter_structures.json

PDF 格式特点：证监会 PDF 的文本提取会产生多行拆分，例如：
  第一章
  总
  则
  第一条
  为规范...
需要跨行拼接才能还原"第一章 总则"。
"""

import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "annual_semi_extraction" / "spec" / "regulatory_texts"
OUTPUT = ROOT / "annual_semi_extraction" / "spec" / "chapter_structures.json"

# 中文数字
CN_NUMS = "一二三四五六七八九十百"

# 结构标记 - 支持两种格式：
# 1. "第一章总则" (章号和标题同行)
# 2. "第一章" (章号单独一行，标题在后续行)
RE_CHAPTER_INLINE = re.compile(rf"^第([{CN_NUMS}]+)章(.+)$")
RE_CHAPTER_MARKER = re.compile(rf"^第[{CN_NUMS}]+章$")
RE_SECTION_INLINE = re.compile(rf"^第([{CN_NUMS}]+)节(.+)$")
RE_SECTION_MARKER = re.compile(rf"^第[{CN_NUMS}]+节$")
RE_ARTICLE_INLINE = re.compile(rf"^第([{CN_NUMS}0-9]+)条(.+)$")
RE_ARTICLE_MARKER = re.compile(rf"^第[{CN_NUMS}0-9]+条$")
RE_ATTACH = re.compile(r"^附件\s*[：:]\s*$|^附件\s*[一二三四五六七八九十\d]+\s*[：:]")


def extract_full_text(pdf_path: Path) -> str:
    """提取 PDF 全文并做基本清洗。"""
    doc = pymupdf.open(str(pdf_path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def extract_structure(pdf_path: Path) -> dict:
    """提取单个 PDF 的章节结构。

    策略：逐行扫描，识别"第X章"/"第X节"/"第X条"标记行，
    支持两种格式：
    1. "第一章总则" (章号和标题同行)
    2. "第一章" (章号单独一行，标题在后续行)
    """
    text = extract_full_text(pdf_path)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    structure = {
        "chapters": [],
        "articles_count": 0,
        "pages": pymupdf.open(str(pdf_path)).page_count,
    }

    current_chapter = None
    current_section = None
    collecting_chapter_name = False
    collecting_section_name = False
    name_parts = []

    def flush_name():
        """把收集到的标题碎片拼成一个完整标题。"""
        nonlocal name_parts
        if not name_parts:
            return ""
        # 单字碎片直接拼接（"总" + "则" -> "总则"）
        result = "".join(name_parts)
        name_parts = []
        return result

    i = 0
    while i < len(lines):
        line = lines[i]

        # 跳过页码行（纯数字且长度<=3）
        if re.match(r"^\d{1,3}$", line):
            i += 1
            continue

        # 检测"第X章" - 同行格式："第一章总则"
        m = RE_CHAPTER_INLINE.match(line)
        if m:
            # flush 上一个章的标题
            if current_chapter and name_parts:
                current_chapter["name"] = flush_name()
                current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"

            marker = f"第{m.group(1)}章"
            name = m.group(2)
            current_chapter = {
                "marker": marker,
                "title": f"{marker} {name}",
                "name": name,
                "sections": [],
                "articles_in_chapter": [],
            }
            structure["chapters"].append(current_chapter)
            current_section = None
            collecting_chapter_name = False
            collecting_section_name = False
            name_parts = []
            i += 1
            continue

        # 检测"第X章" - 单独标记行："第一章"
        if RE_CHAPTER_MARKER.match(line):
            # flush 上一个章的标题
            if current_chapter and name_parts:
                current_chapter["name"] = flush_name()
                current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"

            marker = line
            current_chapter = {
                "marker": marker,
                "title": marker,  # 暂定，等标题碎片收集完再更新
                "name": "",
                "sections": [],
                "articles_in_chapter": [],
            }
            structure["chapters"].append(current_chapter)
            current_section = None
            collecting_chapter_name = True
            collecting_section_name = False
            name_parts = []
            i += 1
            continue

        # 检测"第X节" - 同行格式："第一节 重要提示"
        m = RE_SECTION_INLINE.match(line)
        if m:
            # flush 上一个节的标题
            if current_section and name_parts:
                current_section["name"] = flush_name()
                current_section["title"] = f"{current_section['marker']} {current_section['name']}"

            if current_chapter is None:
                i += 1
                continue

            marker = f"第{m.group(1)}节"
            name = m.group(2)
            section = {
                "marker": marker,
                "title": f"{marker} {name}",
                "name": name,
                "articles_in_section": [],
            }
            current_chapter["sections"].append(section)
            current_section = section
            collecting_section_name = False
            collecting_chapter_name = False
            name_parts = []
            i += 1
            continue

        # 检测"第X节" - 单独标记行："第一节"
        if RE_SECTION_MARKER.match(line):
            # flush 上一个节的标题
            if current_section and name_parts:
                current_section["name"] = flush_name()
                current_section["title"] = f"{current_section['marker']} {current_section['name']}"

            if current_chapter is None:
                i += 1
                continue

            marker = line
            section = {
                "marker": marker,
                "title": marker,
                "name": "",
                "articles_in_section": [],
            }
            current_chapter["sections"].append(section)
            current_section = section
            collecting_section_name = True
            collecting_chapter_name = False
            name_parts = []
            i += 1
            continue

        # 检测"第X条" - 同行格式："第一条 为规范..."
        m = RE_ARTICLE_INLINE.match(line)
        if m:
            # flush 当前标题碎片
            if collecting_chapter_name and current_chapter:
                current_chapter["name"] = flush_name()
                current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"
                collecting_chapter_name = False
            elif collecting_section_name and current_section:
                current_section["name"] = flush_name()
                current_section["title"] = f"{current_section['marker']} {current_section['name']}"
                collecting_section_name = False

            structure["articles_count"] += 1
            article_text = line
            article_entry = {"marker": f"第{m.group(1)}条", "preview": article_text[:120]}

            if current_section is not None:
                current_section["articles_in_section"].append(article_entry)
            elif current_chapter is not None:
                current_chapter["articles_in_chapter"].append(article_entry)

            i += 1
            continue

        # 检测"第X条" - 单独标记行："第一条"
        if RE_ARTICLE_MARKER.match(line):
            # flush 当前标题碎片
            if collecting_chapter_name and current_chapter:
                current_chapter["name"] = flush_name()
                current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"
                collecting_chapter_name = False
            elif collecting_section_name and current_section:
                current_section["name"] = flush_name()
                current_section["title"] = f"{current_section['marker']} {current_section['name']}"
                collecting_section_name = False

            structure["articles_count"] += 1
            article_text = line
            # 收集条文首句（可能在同一行或后续行）
            if i + 1 < len(lines) and not RE_ARTICLE_MARKER.match(lines[i + 1]) \
                    and not RE_ARTICLE_INLINE.match(lines[i + 1]) \
                    and not RE_CHAPTER_MARKER.match(lines[i + 1]) \
                    and not RE_CHAPTER_INLINE.match(lines[i + 1]) \
                    and not RE_SECTION_MARKER.match(lines[i + 1]) \
                    and not RE_SECTION_INLINE.match(lines[i + 1]):
                article_text += " " + lines[i + 1][:80]

            article_entry = {"marker": line, "preview": article_text[:120]}

            if current_section is not None:
                current_section["articles_in_section"].append(article_entry)
            elif current_chapter is not None:
                current_chapter["articles_in_chapter"].append(article_entry)

            i += 1
            continue

        # 检测附件标记（停止提取）
        if RE_ATTACH.match(line) and "本准则" not in line:
            break

        # 普通行：如果在收集标题碎片，加入
        if collecting_chapter_name or collecting_section_name:
            # 跳过明显是正文的行（含标点、长度>30）
            if len(line) > 30 or any(c in line for c in "，。；：、"):
                # 这不是标题碎片，是正文开始
                if collecting_chapter_name and current_chapter:
                    current_chapter["name"] = flush_name()
                    current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"
                    collecting_chapter_name = False
                elif collecting_section_name and current_section:
                    current_section["name"] = flush_name()
                    current_section["title"] = f"{current_section['marker']} {current_section['name']}"
                    collecting_section_name = False
            else:
                name_parts.append(line)

        i += 1

    # 最后一次 flush
    if current_chapter and name_parts:
        current_chapter["name"] = flush_name()
        current_chapter["title"] = f"{current_chapter['marker']} {current_chapter['name']}"
    elif current_section and name_parts:
        current_section["name"] = flush_name()
        current_section["title"] = f"{current_section['marker']} {current_section['name']}"

    return structure


def summarize(structure: dict) -> list[str]:
    """生成人可读的章节清单。"""
    result = []
    for ch in structure["chapters"]:
        result.append(ch["title"])
        for sec in ch.get("sections", []):
            result.append(f"  {sec['title']}")
    return result


def main():
    results = {}

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files")

    for pdf_path in pdf_files:
        print(f"\n{'='*60}")
        print(f"Processing {pdf_path.name}...")
        structure = extract_structure(pdf_path)

        key = pdf_path.stem
        results[key] = structure

        print(f"  {structure['pages']} pages, {len(structure['chapters'])} chapters, "
              f"{structure['articles_count']} articles")
        for line in summarize(structure):
            print(f"  {line}")

    # 写入输出
    output_data = {
        "registry": "nooshare-annual-semi-extraction/chapter-structures",
        "registry_version": 1,
        "authority": "nooshare-design/implementation-docs/nooshare-annual-semi-extraction/deliverables/01-requirement.md (v2) §二 E1",
        "source": "从 annual_semi_extraction/spec/regulatory_texts/*.pdf 提取",
        "note": "纯事实提取，不涉及 reg_version 自变量裁决。用于 E1 判定程序的'应然章节清单'。",
        "structures": results,
    }

    OUTPUT.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
