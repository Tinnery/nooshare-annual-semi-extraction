#!/usr/bin/env python3
"""H2 模式分析脚本：提取第二节子标题并统计频次分布。

用法：
    python scripts/analyze_h2_patterns.py --input-dir <md_dir> --output h2_patterns.json

输出：
    {
        "total_files": 1000,
        "files_with_section2": 950,
        "pattern_distribution": [
            {"pattern": ["一、公司简介", "二、联系人和联系方式", ...], "count": 500, "coverage": 0.526},
            ...
        ],
        "heading_frequency": [
            {"heading": "一、公司简介", "count": 900, "frequency": 0.947},
            ...
        ]
    }
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# "第二节"的正则匹配
RE_SECTION_2 = re.compile(
    r"^#{1,6}\s+第\s*([二2])\s*节",
    re.MULTILINE
)

# "第三节"的正则匹配（用于确定边界）
RE_SECTION_3 = re.compile(
    r"^#{1,6}\s+第\s*([三3])\s*节",
    re.MULTILINE
)

# 子标题识别规则（按优先级排序）
# 1. 中文数字编号：一、二、三、
RE_CN_NUMBERED = re.compile(r"^[ \t]*([一二三四五六七八九十]+)[、．.]\s*(.+)$")
# 2. 阿拉伯数字编号：1. 2. 3. 或 1、2、3、
RE_AR_NUMBERED = re.compile(r"^[ \t]*(\d+)[、．.]\s*(.+)$")
# 3. 括号编号：（一）(一) (1)
RE_BRACKET_NUMBERED = re.compile(r"^[ \t]*[（(]([一二三四五六七八九十\d]+)[)）]\s*(.+)$")
# 4. Markdown 标题：## ###
RE_MD_HEADING = re.compile(r"^(#{2,6})\s+(.+)$")


def extract_section2_content(md_text: str) -> Optional[tuple[str, int, int]]:
    """提取第二节的内容（从第二节开始到第三节之前）。
    
    Returns:
        (content, start_pos, end_pos) 或 None
    """
    # 找第二节的起始位置
    match2 = RE_SECTION_2.search(md_text)
    if not match2:
        return None
    
    start_pos = match2.start()
    
    # 找第三节的起始位置（作为边界）
    match3 = RE_SECTION_3.search(md_text, match2.end())
    if match3:
        end_pos = match3.start()
    else:
        # 如果没有第三节，取到文件末尾
        end_pos = len(md_text)
    
    content = md_text[start_pos:end_pos]
    return content, start_pos, end_pos


def extract_subheadings(content: str) -> list[str]:
    """从第二节内容中提取子标题。
    
    Returns:
        子标题列表（归一化后的文本）
    """
    headings = []
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 尝试匹配各种子标题格式
        heading_text = None
        
        # 1. 中文数字编号
        m = RE_CN_NUMBERED.match(line)
        if m:
            heading_text = m.group(2).strip()
        # 2. 阿拉伯数字编号
        elif not heading_text:
            m = RE_AR_NUMBERED.match(line)
            if m:
                heading_text = m.group(2).strip()
        # 3. 括号编号
        elif not heading_text:
            m = RE_BRACKET_NUMBERED.match(line)
            if m:
                heading_text = m.group(2).strip()
        # 4. Markdown 标题
        elif not heading_text:
            m = RE_MD_HEADING.match(line)
            if m:
                heading_text = m.group(2).strip()
        
        if heading_text:
            # 归一化：去除多余空格、统一标点
            heading_text = re.sub(r'\s+', ' ', heading_text)
            heading_text = heading_text.strip()
            if heading_text and len(heading_text) > 2:  # 过滤太短的标题
                headings.append(heading_text)
    
    return headings


def normalize_pattern(headings: list[str]) -> tuple[str, ...]:
    """将子标题列表归一化为 pattern key。
    
    策略：保留顺序，去除重复，统一格式。
    """
    # 去重但保留顺序
    seen = set()
    unique = []
    for h in headings:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    
    return tuple(unique)


def analyze_h2_patterns(input_dir: Path, output_path: Path):
    """分析 H2 模式分布。"""
    
    # 统计计数器
    total_files = 0
    files_with_section2 = 0
    pattern_counter = Counter()
    heading_counter = Counter()
    
    # 扫描所有 MD 文件
    md_files = list(input_dir.rglob("*.md"))
    print(f"找到 {len(md_files)} 个 MD 文件", file=sys.stderr)
    
    for md_path in md_files:
        total_files += 1
        
        try:
            md_text = md_path.read_text(encoding='utf-8')
        except Exception as e:
            print(f"读取失败: {md_path} - {e}", file=sys.stderr)
            continue
        
        # 提取第二节内容
        result = extract_section2_content(md_text)
        if not result:
            continue
        
        content, start_pos, end_pos = result
        files_with_section2 += 1
        
        # 提取子标题
        headings = extract_subheadings(content)
        if not headings:
            continue
        
        # 归一化为 pattern
        pattern = normalize_pattern(headings)
        pattern_counter[pattern] += 1
        
        # 统计单个标题频次
        for h in headings:
            heading_counter[h] += 1
        
        # 进度提示
        if total_files % 1000 == 0:
            print(f"已处理 {total_files} 个文件...", file=sys.stderr)
    
    # 计算覆盖率
    pattern_distribution = []
    for pattern, count in pattern_counter.most_common():
        coverage = count / files_with_section2 if files_with_section2 > 0 else 0
        pattern_distribution.append({
            "pattern": list(pattern),
            "count": count,
            "coverage": round(coverage, 4)
        })
    
    # 计算累计覆盖率
    cumulative = 0.0
    for item in pattern_distribution:
        cumulative += item["coverage"]
        item["cumulative_coverage"] = round(cumulative, 4)
    
    # 单个标题频次
    heading_frequency = []
    for heading, count in heading_counter.most_common():
        frequency = count / files_with_section2 if files_with_section2 > 0 else 0
        heading_frequency.append({
            "heading": heading,
            "count": count,
            "frequency": round(frequency, 4)
        })
    
    # 输出结果
    result = {
        "total_files": total_files,
        "files_with_section2": files_with_section2,
        "section2_coverage": round(files_with_section2 / total_files, 4) if total_files > 0 else 0,
        "pattern_distribution": pattern_distribution[:100],  # 只保留 top 100
        "heading_frequency": heading_frequency[:100],  # 只保留 top 100
        "unique_patterns": len(pattern_counter),
        "unique_headings": len(heading_counter)
    }
    
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 打印摘要
    print(f"\n=== H2 模式分析完成 ===", file=sys.stderr)
    print(f"总文件数: {total_files}", file=sys.stderr)
    print(f"包含第二节的文件: {files_with_section2} ({result['section2_coverage']:.2%})", file=sys.stderr)
    print(f"唯一 pattern 数: {len(pattern_counter)}", file=sys.stderr)
    print(f"唯一标题数: {len(heading_counter)}", file=sys.stderr)
    
    if pattern_distribution:
        print(f"\nTop 5 patterns:", file=sys.stderr)
        for i, item in enumerate(pattern_distribution[:5], 1):
            print(f"  {i}. count={item['count']}, coverage={item['coverage']:.2%}, cumulative={item['cumulative_coverage']:.2%}", file=sys.stderr)
            print(f"     {item['pattern'][:3]}...", file=sys.stderr)
    
    print(f"\n结果已写入: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="H2 模式分析")
    parser.add_argument("--input-dir", type=Path, required=True, help="MD 文件目录")
    parser.add_argument("--output", type=Path, default=Path("h2_patterns.json"), help="输出文件路径")
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        print(f"错误: 目录不存在: {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    
    analyze_h2_patterns(args.input_dir, args.output)


if __name__ == "__main__":
    main()
