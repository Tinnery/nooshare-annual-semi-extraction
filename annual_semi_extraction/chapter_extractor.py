"""章节提取与规范化模块。

从 MD 文件提取章节标题，并规范化为法定章节名称。
"""

import re
from pathlib import Path
from typing import Optional, Tuple


# 匹配 "第X章 标题" 或 "第X节 标题"
RE_CHAPTER_ZH = re.compile(
    r'^(第[一二三四五六七八九十百零]+[章节])\s*[：:．]?\s*(.+)$',
    re.MULTILINE
)

# 匹配 "# 标题"
RE_H1 = re.compile(r'^#\s+(.+)$', re.MULTILINE)

# 法定章节关键词映射 (标准化名称 -> 关键词列表)
CHAPTER_KEYWORDS = {
    "重要提示": ["重要提示", "目录和释义"],
    "公司简介和主要财务指标": ["公司简介", "主要财务指标", "基本情况"],
    "管理层讨论与分析": ["管理层讨论", "经营情况讨论", "董事会报告"],
    "公司治理": ["公司治理", "治理结构"],
    "环境和社会责任": ["环境和社会责任", "社会责任", "ESG", "可持续发展", "环境与社会责任"],
    "重要事项": ["重要事项", "重大事项"],
    "股份变动及股东情况": ["股份变动", "股东情况", "股本变动"],
    "优先股相关情况": ["优先股"],
    "债券相关情况": ["债券", "公司债"],
    "财务报告": ["财务报告", "财务报表", "审计报告"],
    "备查文件目录": ["备查文件"],
}


def extract_chapters_from_md(md_text: str) -> list[str]:
    """从 MD 文本提取章节标题列表。
    
    Returns:
        章节标题列表，格式为 "第X节 标题" 或 "第X章 标题"
        如 ["第一节 重要提示", "第二节 公司简介和主要财务指标", ...]
    """
    chapters = []
    
    # 优先匹配 "第X章/节 标题" 格式
    for m in RE_CHAPTER_ZH.finditer(md_text):
        marker = m.group(1).strip()
        raw_title = m.group(2).strip()
        # 清理目录页的页码噪声：去除尾部的 ".... 12" 等
        title = re.sub(r'[\.…·\s]+\d+\s*$', '', raw_title).strip()
        if not title:
            continue
        # 返回完整标题（marker + title）
        chapters.append(f"{marker} {title}")
    
    if chapters:
        return chapters
    
    # 回退到 # 标题（无 marker 的情况）
    for m in RE_H1.finditer(md_text):
        title = m.group(1).strip()
        # 跳过非章节标题
        if _is_noise_title(title):
            continue
        chapters.append(title)
    
    return chapters


def _is_noise_title(title: str) -> bool:
    """判断是否为噪声标题（非章节标题）。"""
    noise_patterns = [
        r'^\d{4}年',
        r'^年度报告$',
        r'^半年度报告$',
        r'^目录$',
        r'^备查文件',
        r'^释\s*义$',
        r'^审计',
        r'^审阅',
        r'^公司名',
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


def extract_chapters_from_file(filepath: str) -> list[str]:
    """从 MD 文件提取章节标题。"""
    text = Path(filepath).read_text(encoding='utf-8')
    return extract_chapters_from_md(text)
