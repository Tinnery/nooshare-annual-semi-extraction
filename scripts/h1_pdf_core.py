"""h1_pdf_core.py — PDF 一级标题提取核心（移植自阶段0已验证的 pdf_md_compare_v3.py）

供阶段 1a/1b/2/3 复用。在 v3 基础上增加:
- 年份版本化法定章节集（新旧年报/新旧半年报四套 + 并集）
- 目录页自动识别与解析（三源交叉验证的第三源）
- 纯度/年代/编号连续性等元信息
"""
import re
import difflib
from collections import Counter

try:
    import pymupdf as fitz
except ImportError:
    import fitz

# ---- 编号 / 点线模式 ----
SEC_NUM_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]$')
SEC_FULL_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]')
SEC_PREFIX_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]\s*[:：]?\s*')
DOTS_PAT = re.compile(r'[\.。…·]{2,}\s*[\d]{0,4}\s*$')

CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
          '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14,
          '十五': 15, '十六': 16}

BARE_NUMS = {f'第{n}{s}' for n in CN_NUM for s in ('节', '章')}

# ---- 年份版本化法定章节集 ----
CANON_NEW_ANNUAL = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析', '公司治理',
    '环境和社会责任', '重要事项', '股份变动及股东情况', '优先股相关情况',
    '债券相关情况', '财务报告', '备查文件目录']
CANON_OLD_ANNUAL = [
    '重要提示及目录', '释义及重大风险提示', '公司简介和主要财务指标', '公司业务概要',
    '经营情况讨论与分析', '重要事项', '普通股股份变动及股东情况', '优先股相关情况',
    '董监高情况', '公司治理', '公司债券相关情况', '财务报告', '备查文件目录']
CANON_NEW_SEMI = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析', '公司治理',
    '环境和社会责任', '重要事项', '股份变动及股东情况', '优先股相关情况',
    '债券相关情况', '财务报告', '备查文件目录']
CANON_OLD_SEMI = [
    '重要提示及目录', '公司基本情况', '会计数据和财务指标摘要', '董事会报告', '重要事项',
    '股份变动及股东情况', '优先股相关情况', '董监高情况', '财务报告', '备查文件目录']

ERA_SETS = {
    'new_annual': CANON_NEW_ANNUAL, 'old_annual': CANON_OLD_ANNUAL,
    'new_semi': CANON_NEW_SEMI, 'old_semi': CANON_OLD_SEMI,
}
CANON_UNION = sorted({c for s in ERA_SETS.values() for c in s})


def is_meaningful_title(text, max_len=40):
    if not text or len(text) < 2 or len(text) > max_len:
        return False
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    if cjk < 2:
        return False
    if re.fullmatch(r'[\d\s\.\-—·]+', text):
        return False
    return True


def collect_lines(pdf_path):
    """按文档顺序收集 (size, font, flags, text, page)。

    关键修复（阶段0验证）: 先剥离目录点线再做长度过滤, 否则目录标题行(130+字符)
    被丢 → 目录编号裸留、错拼。同时识别目录页(点线行>=3)。
    """
    doc = fitz.open(pdf_path)
    raw_lines, body_sizes = [], Counter()
    dot_per_page = Counter()
    for pno in range(len(doc)):
        d = doc[pno].get_text('dict')
        for block in d['blocks']:
            if block.get('type') != 0:
                continue
            for line in block['lines']:
                text = ''.join(s['text'] for s in line['spans']).strip()
                if not text:
                    continue
                raw_len = len(text)
                if DOTS_PAT.search(text):
                    dot_per_page[pno + 1] += 1
                clean = DOTS_PAT.sub('', text).strip()
                if not clean or len(clean) > 80:
                    continue
                span = line['spans'][0]
                size = round(span['size'], 1)
                raw_lines.append((size, span['font'], span['flags'], clean, pno + 1))
                if raw_len > 40 and len(clean) > 30:
                    body_sizes[size] += raw_len
    doc.close()

    toc_pages = {p for p, c in dot_per_page.items() if c >= 3}

    # 编号-标题拼接: "第X节"单独成行 → 与下一行合并
    joined, skip_next = [], False
    for i, row in enumerate(raw_lines):
        if skip_next:
            skip_next = False
            continue
        size, font, flags, text, page = row
        if SEC_NUM_PAT.match(text):
            nxt = None
            for j in range(i + 1, min(i + 4, len(raw_lines))):
                cand = raw_lines[j]
                cand_text = DOTS_PAT.sub('', cand[3]).strip()
                if not cand_text:
                    continue
                if SEC_NUM_PAT.match(cand_text) or SEC_FULL_PAT.match(cand_text):
                    break
                nxt = cand
                break
            if nxt:
                merged_text = text + ' ' + DOTS_PAT.sub('', nxt[3]).strip()
                joined.append((max(size, nxt[0]),
                               nxt[1] if flags < nxt[2] else font,
                               max(flags, nxt[2]), merged_text, page))
                skip_next = True
                continue
        joined.append(row)

    return joined, body_sizes, toc_pages


def extract_pdf(pdf_path):
    """三级策略提取一级标题, 返回 (headings, meta)。headings=None 表示失败。"""
    joined, body_sizes, toc_pages = collect_lines(pdf_path)
    if not body_sizes:
        return None, {'error': 'no_body_lines', 'toc_pages': sorted(toc_pages)}
    body_main_size = body_sizes.most_common(1)[0][0]
    meta = {'body_main_size': body_main_size, 'toc_pages': sorted(toc_pages)}

    # 策略1: 编号匹配
    num_rows = []
    for size, font, flags, text, page in joined:
        if SEC_FULL_PAT.match(text):
            clean = DOTS_PAT.sub('', text).strip()
            clean = re.sub(r'\s+', ' ', clean)
            if len(clean) < 45:
                num_rows.append((size, font, flags, clean, page))

    best = {}
    for row in num_rows:
        key = re.sub(r'\s+', '', row[3])
        if key in BARE_NUMS:
            continue
        if key not in best or row[0] > best[key][0]:
            best[key] = row
    dedup_rows = sorted(best.values(), key=lambda r: r[4])

    if len(dedup_rows) >= 5:
        meta['strategy'] = 'numbering'
        meta['n_unique_numbered'] = len(dedup_rows)
        headings = [r[3] for r in dedup_rows]
        _enrich(meta, headings, joined, toc_pages)
        return headings, meta

    # 策略2: 书签
    try:
        doc = fitz.open(pdf_path)
        lv1 = [t[1].strip() for t in doc.get_toc() if t[0] == 1]
        doc.close()
    except Exception:
        lv1 = []
    bm = [b for b in lv1 if is_meaningful_title(b, 30)]
    if 5 <= len(bm) <= 40:
        meta['strategy'] = 'bookmark'
        headings = bm
        _enrich(meta, headings, joined, toc_pages)
        return headings, meta

    # 策略3: 严格字体回退
    strict, seen = [], set()
    for size, font, flags, text, page in joined:
        if size - body_main_size < 3.0 or not is_meaningful_title(text, 30):
            continue
        if any(k in text for k in ['保证', '真实、准确', '承诺']) and len(text) > 25:
            continue
        if text in seen:
            continue
        seen.add(text)
        strict.append(text)
    meta['strategy'] = 'font_fallback'
    return strict, {**meta, 'n_fallback': len(strict)}


def _enrich(meta, headings, joined, toc_pages):
    """纯度 / 年代判定 / 编号连续性 / 目录页标题"""
    norms = [norm_heading(h) for h in headings]

    # 纯度: 提取标题中能对上法定章节并集的比例
    hits = 0
    for pn in norms:
        if not pn:
            continue
        if any(_canon_match(c, pn) for c in CANON_UNION):
            hits += 1
    meta['purity'] = round(hits / max(len([n for n in norms if n]), 1), 3)

    # 年代判定: 哪套版本集命中最多
    era_scores = {}
    for era, cset in ERA_SETS.items():
        matched = sum(1 for c in cset if any(_canon_match(c, pn) for pn in norms if pn))
        era_scores[era] = round(matched / len(cset), 2)
    best_era = max(era_scores, key=era_scores.get)
    meta['era'] = best_era
    meta['era_score'] = era_scores[best_era]
    meta['era_scores'] = era_scores

    # 编号连续性
    seq = []
    for h in headings:
        m = SEC_FULL_PAT.match(h)
        if m:
            num = m.group().replace('第', '').rstrip('节章')
            seq.append(CN_NUM.get(num, 0))
    meta['continuous'] = bool(seq) and seq == list(range(1, len(seq) + 1))
    meta['n_numbered'] = len(seq)

    # 目录页标题（第三源）
    toc, seen = [], set()
    for size, font, flags, text, page in joined:
        if page not in toc_pages:
            continue
        t = DOTS_PAT.sub('', text).strip()
        t = re.sub(r'\s+', ' ', t)
        if SEC_FULL_PAT.match(t) and len(t) < 45:
            key = re.sub(r'\s+', '', t)
            if key not in seen:
                seen.add(key)
                toc.append(t)
    meta['toc_headings'] = toc


def _canon_match(canon, pn):
    cn = norm_heading(canon)
    if not cn or not pn:
        return False
    if cn == pn or pn.startswith(cn) or cn.startswith(pn):
        return True
    if abs(len(cn) - len(pn)) <= 2:
        return difflib.SequenceMatcher(None, cn, pn).ratio() >= 0.85
    return False


def norm_heading(h):
    h = SEC_PREFIX_PAT.sub('', h.strip())
    h = DOTS_PAT.sub('', h)
    h = re.sub(r'\s+', '', h)
    return h


def match_score(md_raw, pdf_norm):
    """MD raw_name 与 PDF 归一化标题的对齐判定"""
    md_n = norm_heading(md_raw)
    if not md_n or not pdf_norm:
        return False
    if pdf_norm == md_n or pdf_norm.startswith(md_n) or md_n.startswith(pdf_norm):
        return True
    if abs(len(md_n) - len(pdf_norm)) <= 2:
        return difflib.SequenceMatcher(None, md_n, pdf_norm).ratio() >= 0.85
    return False
