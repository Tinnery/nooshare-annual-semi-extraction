"""H2 内容抽取核心逻辑。

从 MD 文件中提取"第二节"的完整内容。

设计原则：
- 精确定位：支持多种"第二节"变体（中文数字、阿拉伯数字、空格变体）
- 边界清晰：从"第二节"开始，到"第三节"之前结束
- 结构化输出：包含标题、正文、行号范围、字节偏移
- 可回放：保留 verbatim 原文，支持 M2 验证
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

# "第二节"的正则匹配（支持多种变体）
# 匹配：第二节、第2节、第 二 节、第 2 节 等
RE_SECTION_2 = re.compile(
    r"^#{1,6}\s+第\s*([二2])\s*节\s*(.*)$",
    re.MULTILINE
)

# "第三节"的正则匹配（用于确定边界）
RE_SECTION_3 = re.compile(
    r"^#{1,6}\s+第\s*([三3])\s*节",
    re.MULTILINE
)

# 任意"第X节"的正则（用于更灵活的边界检测）
RE_ANY_SECTION = re.compile(
    r"^#{1,6}\s+第\s*([一二三四五六七八九十0-9]+)\s*节",
    re.MULTILINE
)


def cn_to_int(s: str) -> int | None:
    """中文数字 → int（支持 十/十一/二十 等）。"""
    CN_DIGIT = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "壹": 1, "贰": 2, "叁": 3,
        "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    }
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


def sha256_text(text: str) -> str:
    """计算文本的 SHA256 哈希。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_h2(md_path: Path) -> dict | None:
    """从单个 MD 文件中抽取 H2（第二节）内容。

    Args:
        md_path: MD 文件路径

    Returns:
        包含 H2 内容的字典，结构如下：
        {
            "slot_key": "000001_2024_4",
            "path": "/path/to/file.md",
            "source_sha256": "...",
            "h2_found": True,
            "h2_title": "第二节 公司简介和主要财务指标",
            "h2_name": "公司简介和主要财务指标",
            "h2_start_line": 45,
            "h2_end_line": 120,
            "h2_start_byte": 1234,
            "h2_end_byte": 5678,
            "h2_content": "...",
            "h2_content_sha256": "...",
            "n_h2_lines": 75,
            "n_h2_bytes": 4444,
            "next_section_marker": "第三节",
            "extraction_method": "section_boundary"
        }
        如果未找到第二节，返回 None。
    """
    if not md_path.exists():
        return None

    # 解析 slot_key
    slot_key = _slot_key_from_path(md_path)
    if slot_key is None:
        return None

    # 读取文件
    raw = md_path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    source_sha256 = sha256_text(text)

    lines = text.splitlines(keepends=True)

    # 查找"第二节"
    h2_start_line = None
    h2_start_byte = 0
    h2_title = None
    h2_name = None

    byte_offset = 0
    for lineno, line in enumerate(lines, start=1):
        m = RE_SECTION_2.match(line)
        if m:
            h2_start_line = lineno
            h2_start_byte = byte_offset
            h2_title = line.strip()
            h2_name = m.group(2).strip()
            break
        byte_offset += len(line.encode("utf-8"))

    if h2_start_line is None:
        return {
            "slot_key": slot_key,
            "path": str(md_path),
            "source_sha256": source_sha256,
            "h2_found": False,
            "extraction_method": "none",
        }

    # 查找"第三节"或下一个章节作为边界
    h2_end_line = len(lines)
    h2_end_byte = len(raw)
    next_section_marker = None

    byte_offset = 0
    for lineno, line in enumerate(lines, start=1):
        if lineno <= h2_start_line:
            byte_offset += len(line.encode("utf-8"))
            continue

        # 检查是否是"第三节"或其他章节
        m3 = RE_SECTION_3.match(line)
        if m3:
            h2_end_line = lineno
            h2_end_byte = byte_offset
            next_section_marker = "第三节"
            break

        # 检查是否是其他"第X节"（X > 2）
        m_any = RE_ANY_SECTION.match(line)
        if m_any:
            section_num = cn_to_int(m_any.group(1))
            if section_num is not None and section_num > 2:
                h2_end_line = lineno
                h2_end_byte = byte_offset
                next_section_marker = f"第{m_any.group(1)}节"
                break

        byte_offset += len(line.encode("utf-8"))

    # 提取 H2 内容
    h2_lines = lines[h2_start_line - 1 : h2_end_line - 1]
    h2_content = "".join(h2_lines)
    h2_content_sha256 = sha256_text(h2_content)

    return {
        "slot_key": slot_key,
        "path": str(md_path),
        "source_sha256": source_sha256,
        "h2_found": True,
        "h2_title": h2_title,
        "h2_name": h2_name,
        "h2_start_line": h2_start_line,
        "h2_end_line": h2_end_line,
        "h2_start_byte": h2_start_byte,
        "h2_end_byte": h2_end_byte,
        "h2_content": h2_content,
        "h2_content_sha256": h2_content_sha256,
        "n_h2_lines": len(h2_lines),
        "n_h2_bytes": len(h2_content.encode("utf-8")),
        "next_section_marker": next_section_marker,
        "extraction_method": "section_boundary",
    }


def extract_h2_batch(
    input_dir: Path,
    output: Path,
    failures: Path,
    limit: int = 0,
    offset: int = 0,
    append: bool = False,
) -> dict:
    """批量抽取 H2 内容。

    Args:
        input_dir: 输入目录（包含 MD 文件的目录，递归扫描）
        output: 输出 JSONL 文件路径
        failures: 失败记录输出路径
        limit: 限制处理文件数（0=不限制）
        offset: 跳过前 N 个文件
        append: 追加模式

    Returns:
        统计信息字典
    """
    # 收集所有 MD 文件
    md_files = sorted(input_dir.rglob("*.md"))
    if offset > 0:
        md_files = md_files[offset:]
    if limit > 0:
        md_files = md_files[:limit]

    n_files = len(md_files)
    n_ok = 0
    n_not_found = 0
    n_errors = 0

    # 打开输出文件
    mode = "a" if append else "w"
    with output.open(mode, encoding="utf-8") as fout, \
         failures.open(mode, encoding="utf-8") as ffail:

        for md_path in md_files:
            try:
                result = extract_h2(md_path)
                if result is None:
                    n_errors += 1
                    ffail.write(json.dumps({
                        "path": str(md_path),
                        "error": "extract_h2 returned None",
                    }, ensure_ascii=False) + "\n")
                elif result.get("h2_found"):
                    n_ok += 1
                    fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                else:
                    n_not_found += 1
                    ffail.write(json.dumps(result, ensure_ascii=False) + "\n")
            except Exception as e:
                n_errors += 1
                ffail.write(json.dumps({
                    "path": str(md_path),
                    "error": str(e),
                }, ensure_ascii=False) + "\n")

    return {
        "n_files": n_files,
        "n_ok": n_ok,
        "n_not_found": n_not_found,
        "n_errors": n_errors,
    }


def _slot_key_from_path(p: Path) -> str | None:
    """从路径解析 slot_key: published/<code>/<code>_<year>_<period>.md"""
    m = re.match(r"^(\d{6})_(\d{4})_([24])\.md$", p.name)
    if not m:
        return None
    return f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
