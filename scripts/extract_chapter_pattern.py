"""从 MD 文件提取章节标题 pattern，用于 E1 判定。

支持两种格式：
1. 第X章 格式（年报常见）：第一章 公司简介 / 第一节 释义
2. # 标题 格式（半年报常见）
"""
import re
import os
from typing import Optional
from pathlib import Path


# 匹配 "第X章 标题" 或 "第X节 标题"
RE_CHAPTER_ZH = re.compile(
    r'^第[一二三四五六七八九十百零]+[章节]\s*[：:．]?\s*(.+)$',
    re.MULTILINE
)

# 匹配 "# 标题"
RE_H1 = re.compile(r'^#\s+(.+)$', re.MULTILINE)

# 匹配 "## 标题"
RE_H2 = re.compile(r'^##\s+(.+)$', re.MULTILINE)

# 法定章节标题关键词（用于匹配规范化后的标题）
CHAPTER_KEYWORDS = {
    "公司简介": ["公司简介", "基本情况", "公司概况"],
    "会计数据和财务指标": ["会计数据", "财务指标", "主要财务数据"],
    "管理层讨论与分析": ["管理层讨论", "经营情况讨论", "董事会报告"],
    "公司治理": ["公司治理", "治理结构"],
    "环境和社会责任": ["环境和社会责任", "社会责任", "ESG", "可持续发展"],
    "重要事项": ["重要事项", "重大事项"],
    "股份变动及股东情况": ["股份变动", "股东情况", "股本变动"],
    "优先股相关情况": ["优先股"],
    "债券相关情况": ["债券", "公司债"],
    "财务报告": ["财务报告", "财务报表", "审计报告"],
    "释义": ["释义", "名词解释", "术语"],
}


def extract_chapters_from_md(md_text: str) -> list[dict]:
    """从 MD 文本提取章节标题列表。
    
    Returns:
        [{"marker": "第一章", "title": "公司简介", "raw": "第一章  公司简介"}, ...]
    """
    chapters = []
    
    # 优先匹配 "第X章/节 标题" 格式
    for m in RE_CHAPTER_ZH.finditer(md_text):
        marker = m.group(0).split(m.group(1))[0].strip()
        raw_title = m.group(1).strip()
        # 清理目录页的页码噪声：去除尾部的 ".... 12" 等
        title = re.sub(r'[\.…·\s]+\d+\s*$', '', raw_title).strip()
        if not title:
            continue
        chapters.append({
            "marker": marker,
            "title": title,
            "raw": m.group(0).strip(),
        })
    
    if chapters:
        return chapters
    
    # 回退到 # 标题
    for m in RE_H1.finditer(md_text):
        title = m.group(1).strip()
        # 跳过非章节标题
        if _is_noise_title(title):
            continue
        chapters.append({
            "marker": "#",
            "title": title,
            "raw": m.group(0).strip(),
        })
    
    return chapters


def _is_noise_title(title: str) -> bool:
    """判断是否为噪声标题（非章节标题）。"""
    noise_patterns = [
        r'^\d{4}年',  # 2024年年度报告
        r'^年度报告$',
        r'^半年度报告$',
        r'^重要提示$',
        r'^目录$',
        r'^备查文件',
        r'^释\s*义$',
        r'^审计',
        r'^审阅',
        r'^公司名',  # 公司名称标题
        r'^股份有限',
    ]
    for p in noise_patterns:
        if re.match(p, title):
            return True
    return False


def normalize_chapter_title(title: str) -> Optional[str]:
    """将章节标题规范化为法定名称。
    
    Returns:
        规范化后的名称，或 None（无法匹配）
    """
    title_lower = title.lower().strip()
    
    for standard_name, keywords in CHAPTER_KEYWORDS.items():
        for kw in keywords:
            if kw in title_lower or kw.lower() in title_lower:
                return standard_name
    
    return None


def extract_chapters_from_file(filepath: str) -> list[dict]:
    """从 MD 文件提取章节标题。"""
    text = Path(filepath).read_text(encoding='utf-8')
    return extract_chapters_from_md(text)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python extract_chapter_pattern.py <md_file> [<md_file2> ...]")
        sys.exit(1)
    
    for f in sys.argv[1:]:
        if not os.path.exists(f):
            print(f"NOT FOUND: {f}")
            continue
        
        print(f"\n=== {os.path.basename(f)} ===")
        chapters = extract_chapters_from_file(f)
        print(f"提取到 {len(chapters)} 个章节:")
        for c in chapters:
            norm = normalize_chapter_title(c["title"])
            norm_str = f" -> {norm}" if norm else ""
            print(f"  {c['marker']:6} | {c['title'][:50]}{norm_str}")
