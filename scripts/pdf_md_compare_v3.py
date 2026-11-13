"""
PDF vs MD 对比 v3 (最终版):
1. 修复编号-标题分行: "第X节"单独成行时与下一行拼接
2. 修复目录页污染: 按字号优先保留正文版本 (正文标题字号 > 目录条目字号)
3. 法定章节模糊匹配 (环境与社会责任 vs 环境和社会责任)
"""
import json, os, re, time, difflib
from collections import Counter

# 可用环境变量覆盖 (跨主机运行: pro 上设 H1_PDF_DIR / H1_OUT_SUFFIX)
TEMP = os.environ.get('H1_PDF_DIR', os.environ.get('TEMP', r'C:\Users\travis\AppData\Local\Temp'))
PDF_DIR = TEMP if os.path.isdir(TEMP) else os.path.join(TEMP, 'pdf_validation_samples')
OUT_SUFFIX = os.environ.get('H1_OUT_SUFFIX', '')

CANONICAL_SECTIONS = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析',
    '公司治理', '环境和社会责任', '重要事项', '股份变动及股东情况',
    '优先股相关情况', '债券相关情况', '财务报告',
]

SEC_NUM_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]$')          # 仅编号
SEC_FULL_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]')          # 编号开头
SEC_PREFIX_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]\s*[:：]?\s*')
DOTS_PAT = re.compile(r'[\.。…·]{2,}\s*[\d]{0,4}\s*$')                        # 目录点线+页码


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
    """按文档顺序收集 (size, font, flags, text, page), 并做编号-标题拼接

    关键: 先剥离目录点线再做长度过滤, 否则目录标题行(130+字符)被丢,
    导致目录页编号行无法拼接而裸留、甚至错拼到下一节名(备查文件目录 bug)。
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    doc = fitz.open(pdf_path)
    raw_lines = []
    body_sizes = Counter()
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
                # 先清洗点线/页码, 再判断长度
                clean = DOTS_PAT.sub('', text).strip()
                if not clean or len(clean) > 80:
                    continue
                span = line['spans'][0]
                size = round(span['size'], 1)
                raw_lines.append((size, span['font'], span['flags'], clean, pno + 1))
                # 正文主导字号: 用清洗前的原始长度 (正文段落才是长行, 点线行是目录)
                if raw_len > 40 and len(clean) > 30:
                    body_sizes[size] += raw_len
    doc.close()

    # 编号-标题拼接: "第X节"单独成行 → 与下一行合并
    joined = []
    skip_next = False
    for i, row in enumerate(raw_lines):
        if skip_next:
            skip_next = False
            continue
        size, font, flags, text, page = row
        if SEC_NUM_PAT.match(text):
            # 找下一行 (同页或跨页)
            nxt = None
            for j in range(i + 1, min(i + 4, len(raw_lines))):
                cand = raw_lines[j]
                cand_text = DOTS_PAT.sub('', cand[3]).strip()
                if not cand_text:
                    continue
                if SEC_NUM_PAT.match(cand_text) or SEC_FULL_PAT.match(cand_text):
                    break  # 下一行还是编号 → 不拼
                nxt = cand
                break
            if nxt:
                merged_text = text + ' ' + DOTS_PAT.sub('', nxt[3]).strip()
                merged = (max(size, nxt[0]), nxt[1] if flags < nxt[2] else font, max(flags, nxt[2]), merged_text, page)
                joined.append(merged)
                skip_next = True
                continue
        joined.append(row)

    return joined, body_sizes


def extract_h1_from_pdf_v3(pdf_path):
    joined, body_sizes = collect_lines(pdf_path)
    if not body_sizes:
        return None, {'error': '无正文行'}
    body_main_size = body_sizes.most_common(1)[0][0]

    # 策略1: 编号匹配 (拼接后), 清洗目录点线
    num_rows = []
    for size, font, flags, text, page in joined:
        if SEC_FULL_PAT.match(text):
            clean = DOTS_PAT.sub('', text).strip()
            clean = re.sub(r'\s+', ' ', clean)
            if len(clean) < 45:
                num_rows.append((size, font, flags, clean, page))

    # 去重: 键=去空白全文(保留编号, 目录版与正文版同键), 保留字号最大的 (正文 > 目录)
    best = {}
    for row in num_rows:
        key = re.sub(r'\s+', '', row[3])
        if key in ('第一节', '第二节', '第三节', '第四节', '第五节',
                   '第六节', '第七节', '第八节', '第九节', '第十节',
                   '第十一节', '第十二节', '第十三节', '第十四节', '第十五节',
                   '第十六节', '第一章', '第二章', '第三章', '第四章', '第五章',
                   '第六章', '第七章', '第八章', '第九章', '第十章'):
            continue  # 裸编号无标题 → 丢弃
        if key not in best or row[0] > best[key][0]:
            best[key] = row
    dedup_rows = sorted(best.values(), key=lambda r: r[4])  # 按页码排序

    if len(dedup_rows) >= 5:
        meta = {'strategy': 'numbering', 'body_main_size': body_main_size,
                'n_unique_numbered': len(dedup_rows)}
        headings = [r[3] for r in dedup_rows]
        return headings, meta

    # 策略2: 书签
    try:
        import pymupdf as fitz
        doc = fitz.open(pdf_path)
        lv1_bookmarks = [t[1].strip() for t in doc.get_toc() if t[0] == 1]
        doc.close()
    except Exception:
        lv1_bookmarks = []
    bm_clean = [b for b in lv1_bookmarks if is_meaningful_title(b, 30)]
    if len(bm_clean) >= 5 and len(bm_clean) <= 40:
        meta = {'strategy': 'bookmark', 'body_main_size': body_main_size}
        return bm_clean, meta

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
        strict.append((size, font, flags, text, page))
    meta = {'strategy': 'font_fallback', 'body_main_size': body_main_size}
    return [r[3] for r in strict], meta


def norm_heading(h):
    h = SEC_PREFIX_PAT.sub('', h.strip())
    h = DOTS_PAT.sub('', h)
    h = re.sub(r'\s+', '', h)
    return h


def fuzzy_eq(a, b, threshold=0.8):
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def match_score(md_raw, pdf_norm):
    md_n = norm_heading(md_raw)
    if not md_n or not pdf_norm:
        return False
    if pdf_norm == md_n or pdf_norm.startswith(md_n) or md_n.startswith(pdf_norm):
        return True
    # 处理个别字符差异 (环境与社会责任 vs 环境和社会责任)
    if abs(len(md_n) - len(pdf_norm)) <= 2:
        return difflib.SequenceMatcher(None, md_n, pdf_norm).ratio() >= 0.85
    return False


def main():
    with open('data/pdf_validation_results.json', 'r', encoding='utf-8') as f:
        results = json.load(f)

    # 重跑全部 extracted
    print('重跑 v3 提取...')
    n_ok = 0
    for r in results:
        if r['status'] != 'extracted' or not r.get('pdf_path'):
            continue
        try:
            headings, meta = extract_h1_from_pdf_v3(r['pdf_path'])
            if headings is not None:
                r['pdf_headings'] = headings
                r['pdf_meta'] = meta
                n_ok += 1
        except Exception as e:
            print(f'  {r["stock_code"]}: {e}')
    print(f'  v3 提取完成: {n_ok}')

    # 对比
    comparison = []
    for r in results:
        if r['status'] != 'extracted':
            continue
        md_h = r.get('md_headings', [])
        pdf_h = r.get('pdf_headings', [])
        pdf_norms = [norm_heading(h) for h in pdf_h]

        md_matched, md_unmatched = [], []
        for raw in md_h:
            hit = next((pn for pn in pdf_norms if match_score(raw, pn)), None)
            (md_matched if hit else md_unmatched).append(raw)

        canon_hits = [pn for pn in pdf_norms
                      if any(fuzzy_eq(norm_heading(c), pn) or
                             (len(norm_heading(c)) >= 4 and (norm_heading(c) in pn or pn.startswith(norm_heading(c))))
                             for c in CANONICAL_SECTIONS)]
        canon_rate = len(canon_hits) / max(len(pdf_norms), 1)

        nums = [SEC_FULL_PAT.match(h).group() for h in pdf_h if SEC_FULL_PAT.match(h)]
        def cn2int(s):
            cn_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7,
                      '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12, '十三': 13,
                      '十四': 14, '十五': 15, '十六': 16}
            return cn_map.get(s.replace('第', '').replace('节', '').replace('章', ''), 0)
        seq = [cn2int(n) for n in nums]
        consecutive = seq == list(range(1, len(seq) + 1)) if seq else False

        comparison.append({
            'stock_code': r['stock_code'], 'year': r['report_year'], 'period': r['period'],
            'layer': r.get('layer'), 'md_method': r.get('extraction_method'),
            'md_n': len(md_h), 'pdf_n': len(pdf_h),
            'md_matched_n': len(md_matched), 'md_unmatched_n': len(md_unmatched),
            'md_unmatched_titles': md_unmatched[:12],
            'strategy': r.get('pdf_meta', {}).get('strategy'),
            'canon_rate': round(canon_rate, 3), 'canon_hits': canon_hits,
            'numbering_consecutive': consecutive,
            'md_headings': md_h, 'pdf_headings': pdf_h,
        })

    with open(f'data/pdf_validation_results{OUT_SUFFIX}.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(f'data/pdf_vs_md_comparison{OUT_SUFFIX}.json', 'w', encoding='utf-8') as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    # 报告
    print(f'\n{"="*108}')
    print('PDF vs MD 对比报告 (v3: 编号拼接+目录去污+模糊法定匹配)')
    print(f'{"="*108}')
    print(f'{"代码":<8} {"年":<5} {"期":<3} {"层":<18} {"策略":<13} {"MD#":>4} {"PDF#":>5} {"MD命中":>6} {"法定率":>6} {"连续":<4}')
    print('-' * 108)
    for c in comparison:
        strat = c['strategy'] or '-'
        consec = 'Y' if c['numbering_consecutive'] else 'N'
        print(f'{c["stock_code"]:<8} {c["year"]:<5} {c["period"]:<3} {c["layer"]:<18} {strat:<13} '
              f'{c["md_n"]:>4} {c["pdf_n"]:>5} {c["md_matched_n"]:>6} {c["canon_rate"]:>6.0%} {consec:<4}')

    tot = len(comparison)
    strat_counts = Counter(c['strategy'] for c in comparison)
    print(f'\n策略分布: {dict(strat_counts)}')

    std = [c for c in comparison if c['strategy'] == 'numbering']
    print(f'\n标准格式样本 (编号策略): {len(std)} 份')
    if std:
        md_tot = sum(c['md_n'] for c in std)
        hit_tot = sum(c['md_matched_n'] for c in std)
        consec_n = sum(1 for c in std if c['numbering_consecutive'])
        avg_canon = sum(c['canon_rate'] for c in std) / len(std)
        perfect = sum(1 for c in std if c['canon_rate'] == 1.0)
        print(f'  PDF 侧: 平均标题数 {sum(c["pdf_n"] for c in std)/len(std):.1f}, '
              f'法定章节纯度均值 {avg_canon:.1%}, 纯度100%样本 {perfect}/{len(std)}, 编号连续 {consec_n}/{len(std)}')
        print(f'  MD 侧: 标题总数 {md_tot}, 与PDF对齐 {hit_tot} ({hit_tot/max(md_tot,1)*100:.1f}%)')

        print(f'\n  MD 分层表现 (标准格式内):')
        for layer in ['ch_zh_complete', 'ch_zh_incomplete', 'md_h1_incomplete',
                      'md_h1_complete', 'none_incomplete', 'cn_dun']:
            lc = [c for c in std if c['layer'] == layer]
            if not lc:
                continue
            lm = sum(c['md_n'] for c in lc)
            lh = sum(c['md_matched_n'] for c in lc)
            print(f'    {layer:<18} {len(lc)}份: MD总数{lm}, 对齐{lh} ({lh/max(lm,1)*100:.0f}%)')

    # 未对齐 MD 标题抽样 (噪声证据)
    print(f'\nMD 未对齐标题示例 (前8份标准格式样本):')
    shown = 0
    for c in std:
        if c['md_unmatched_titles'] and shown < 8:
            print(f'  {c["stock_code"]} {c["year"]}-{c["period"]}:')
            for t in c['md_unmatched_titles'][:4]:
                print(f'    [{t[:55]}]')
            shown += 1


if __name__ == '__main__':
    main()
