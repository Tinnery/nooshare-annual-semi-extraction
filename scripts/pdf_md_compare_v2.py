"""
PDF vs MD 对比 v2:
1. 重跑 PDF 提取: 编号匹配 → 书签次通道 → 严格字体回退
2. 归一化对比: 剥离"第X节"前缀 + 前缀包含匹配(处理拼接噪声)
3. 修复 orgid 缺失, 重试 not_found
"""
import json, os, re, time
import urllib.request, urllib.parse
from collections import Counter

TEMP = os.environ.get('TEMP', r'C:\Users\travis\AppData\Local\Temp')
PDF_DIR = os.path.join(TEMP, 'pdf_validation_samples')
CNINFO_SEARCH = 'http://www.cninfo.com.cn/new/information/topSearch/detailOfQuery'
CNINFO_ANNOUNCE = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
CNINFO_STATIC = 'http://static.cninfo.com.cn/'

# 证监会准则法定必备章节 (2021修订, 封闭集)
CANONICAL_SECTIONS = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析',
    '公司治理', '环境和社会责任', '重要事项', '股份变动及股东情况',
    '优先股相关情况', '债券相关情况', '财务报告',
]

SEC_NUM_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]')
SEC_PREFIX_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]\s*[:：]?\s*')


def get_exchange(code):
    if code.startswith(('000', '002', '003', '300', '301')):
        return 'szse'
    elif code.startswith(('600', '601', '603', '688')):
        return 'sse'
    return 'unknown'


def query_orgid(stock_code):
    data = urllib.parse.urlencode({'keyWord': stock_code, 'maxSecNum': 3, 'maxListNum': 3}).encode()
    req = urllib.request.Request(CNINFO_SEARCH, data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    for item in d.get('keyBoardList', []):
        if item['code'] == stock_code:
            return item['orgId']
    return None


def query_announcements_by_keyword(stock_code, orgid, report_year, period):
    exchange = get_exchange(stock_code)
    column = 'szse' if exchange == 'szse' else 'sse'
    if period == 4:
        kw = '年度报告'
        se_start, se_end = f'{report_year + 1}-01-01', f'{report_year + 1}-06-30'
    else:
        kw = '半年度报告'
        se_start, se_end = f'{report_year}-01-01', f'{report_year}-12-31'

    data = urllib.parse.urlencode({
        'pageNum': 1, 'pageSize': 30, 'column': column, 'tabName': 'fulltext',
        'stock': f'{stock_code},{orgid}', 'searchkey': kw, 'secid': '',
        'category': '', 'trade': '', 'seDate': f'{se_start}~{se_end}'
    }).encode()

    req = urllib.request.Request(CNINFO_ANNOUNCE, data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())

    anns = d.get('announcements') or []
    exclude = ['摘要', '英文', '已取消', '意见', '提示性', '答说明', '问询']
    period_name = '年度报告' if period == 4 else '半年度报告'

    for a in anns:
        title = a.get('announcementTitle', '')
        if kw not in title and period_name not in title:
            continue
        if any(ex in title for ex in exclude):
            continue
        adjunct = a.get('adjunctUrl', '')
        if adjunct and adjunct.lower().endswith('.pdf'):
            return CNINFO_STATIC + adjunct, title
    return None, None


def download_pdf(url, stock_code, report_year, period):
    fn = f'{stock_code}_{report_year}_{period}.pdf'
    out_path = os.path.join(PDF_DIR, fn)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
        return out_path
    urllib.request.urlretrieve(url, out_path)
    return out_path


def is_meaningful_title(text):
    """过滤纯数字/符号/过短的行"""
    if not text or len(text) < 2 or len(text) > 40:
        return False
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    if cjk < 2:
        return False
    if re.fullmatch(r'[\d\s\.\-—·]+', text):
        return False
    return True


def extract_h1_from_pdf_v2(pdf_path):
    """三级策略: 编号匹配 → 书签 → 严格字体回退"""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    lv1_bookmarks = [t[1].strip() for t in toc if t[0] == 1]

    all_lines = []
    body_sizes = Counter()
    for pno in range(len(doc)):
        d = doc[pno].get_text('dict')
        for block in d['blocks']:
            if block.get('type') != 0:
                continue
            for line in block['lines']:
                text = ''.join(s['text'] for s in line['spans']).strip()
                if not text or len(text) > 80:
                    continue
                span = line['spans'][0]
                size = round(span['size'], 1)
                all_lines.append((size, span['font'], span['flags'], text, pno + 1))
                if len(text) > 40:
                    body_sizes[size] += len(text)
    doc.close()

    if not body_sizes:
        return None, None, {'error': '无正文行'}
    body_main_size = body_sizes.most_common(1)[0][0]

    def make_cands(rows, source):
        return [{'text': t, 'size': sz, 'page': pg, 'source': source}
                for sz, f, fl, t, pg in rows]

    # ── 策略1: 编号匹配 (标准格式) ──
    num_rows = [(s, f, fl, t, p) for s, f, fl, t, p in all_lines
                if SEC_NUM_PAT.match(t) and len(t) < 40]
    # 同一标题多次出现时只保留首次 (目录页 vs 正文页: 取第二次出现, 正文)
    seen, dedup_rows = set(), []
    for row in num_rows:
        key = row[3]
        if key in seen:
            continue
        seen.add(key)
        dedup_rows.append(row)

    if len(dedup_rows) >= 5:
        cands = make_cands(dedup_rows, 'numbering')
        meta = {'strategy': 'numbering', 'body_main_size': body_main_size,
                'has_bookmarks': len(toc) > 0, 'n_l1_bookmarks': len(lv1_bookmarks)}
        return [c['text'] for c in cands], cands, meta

    # ── 策略2: 书签 (H股/杂志风格) ──
    bm_clean = [b for b in lv1_bookmarks if is_meaningful_title(b)]
    if len(bm_clean) >= 5 and len(bm_clean) <= 40:
        meta = {'strategy': 'bookmark', 'body_main_size': body_main_size,
                'has_bookmarks': True, 'n_l1_bookmarks': len(lv1_bookmarks)}
        return bm_clean, [{'text': b, 'size': None, 'page': None, 'source': 'bookmark'}
                          for b in bm_clean], meta

    # ── 策略3: 严格字体回退 ──
    strict = []
    seen = set()
    for size, font, flags, text, page in all_lines:
        if size - body_main_size < 3.0:
            continue
        if not is_meaningful_title(text):
            continue
        # 排除拼接噪声(长行含声明)
        if any(k in text for k in ['保证', '真实、准确', '承诺']) and len(text) > 25:
            continue
        if text in seen:
            continue
        seen.add(text)
        strict.append((size, font, flags, text, page))

    meta = {'strategy': 'font_fallback', 'body_main_size': body_main_size,
            'has_bookmarks': len(toc) > 0, 'n_l1_bookmarks': len(lv1_bookmarks)}
    cands = make_cands(strict, 'font_fallback')
    return [c['text'] for c in cands], cands, meta


def norm_heading(h):
    """归一化: 剥离'第X节'前缀、空白"""
    h = SEC_PREFIX_PAT.sub('', h.strip())
    h = re.sub(r'\s+', '', h)
    return h


def match_score(md_raw, pdf_norm):
    """前缀包含匹配: 处理拼接噪声 (md= 标题+正文拼接, pdf= 纯标题)"""
    md_n = norm_heading(md_raw)
    if not md_n or not pdf_norm:
        return False
    return pdf_norm == md_n or pdf_norm.startswith(md_n) or md_n.startswith(pdf_norm)


def main():
    with open('data/pdf_validation_results.json', 'r', encoding='utf-8') as f:
        results = json.load(f)

    # ── 1. 重试 not_found (修复 orgid) ──
    not_found = [r for r in results if r['status'] == 'not_found']
    print(f'重试 {len(not_found)} 份 not_found ...')
    recovered = 0
    for i, r in enumerate(not_found):
        code, year, period = r['stock_code'], r['report_year'], r['period']
        try:
            orgid = query_orgid(code)
            if not orgid:
                continue
            url, title = query_announcements_by_keyword(code, orgid, year, period)
            if url:
                path = download_pdf(url, code, year, period)
                headings, cands, meta = extract_h1_from_pdf_v2(path)
                if headings is not None:
                    r.update({'pdf_url': url, 'pdf_title': title, 'pdf_path': path,
                              'pdf_headings': headings, 'pdf_meta': meta, 'status': 'extracted'})
                    recovered += 1
                else:
                    r.update({'pdf_meta': meta, 'status': 'extract_failed'})
        except Exception as e:
            print(f'  {code} {year}-{period}: {type(e).__name__}: {e}')
        time.sleep(0.4)
    print(f'恢复成功: {recovered}/{len(not_found)}')

    # ── 2. 重跑全部 extracted 的提取 (v2策略) ──
    print(f'\n重跑 v2 提取...')
    n_re = 0
    for r in results:
        if r['status'] not in ('extracted',) or not r.get('pdf_path'):
            continue
        try:
            headings, cands, meta = extract_h1_from_pdf_v2(r['pdf_path'])
            if headings is not None:
                r['pdf_headings'] = headings
                r['pdf_meta'] = meta
                n_re += 1
        except Exception as e:
            print(f'  {r["stock_code"]}: {e}')
    print(f'  v2 提取完成: {n_re} 份')

    # ── 3. 归一化逐份对比 ──
    comparison = []
    for r in results:
        if r['status'] != 'extracted':
            continue
        md_h = r.get('md_headings', [])
        pdf_h = r.get('pdf_headings', [])
        pdf_norms = [norm_heading(h) for h in pdf_h]

        # MD→PDF 对齐 (处理拼接噪声)
        md_matched, md_unmatched = [], []
        for raw in md_h:
            hit = next((pn for pn in pdf_norms if match_score(raw, pn)), None)
            if hit:
                md_matched.append(raw)
            else:
                md_unmatched.append(raw)

        # PDF→法定封闭集
        canon_hits = [pn for pn in pdf_norms
                      if any(norm_heading(c) == pn or norm_heading(c) in pn or pn.startswith(norm_heading(c))
                             for c in CANONICAL_SECTIONS)]
        canon_rate = len(canon_hits) / max(len(pdf_norms), 1)

        # 编号连续性: 第一节..第N节 无跳号
        nums = [SEC_NUM_PAT.match(h).group() for h in pdf_h if SEC_NUM_PAT.match(h)]
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
            'has_bookmarks': r.get('pdf_meta', {}).get('has_bookmarks', False),
            'canon_rate': round(canon_rate, 3),
            'canon_hits': canon_hits,
            'numbering_consecutive': consecutive,
            'md_headings': md_h, 'pdf_headings': pdf_h,
        })

    # ── 4. 保存 + 报告 ──
    with open('data/pdf_validation_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open('data/pdf_vs_md_comparison.json', 'w', encoding='utf-8') as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    status_counts = Counter(r['status'] for r in results)
    print(f'\n{"="*108}')
    print(f'PDF vs MD 对比报告 (v2, 归一化后)')
    print(f'{"="*108}')
    print(f'样本状态: {dict(status_counts)}')
    print(f'\n{"代码":<8} {"年":<5} {"期":<3} {"层":<18} {"策略":<14} {"MD#":>4} {"PDF#":>5} {"MD命中":>6} {"法定率":>6} {"连续":<4}')
    print('-' * 108)

    for c in comparison:
        strat = c['strategy'] or '-'
        consec = 'Y' if c['numbering_consecutive'] else 'N'
        print(f'{c["stock_code"]:<8} {c["year"]:<5} {c["period"]:<3} {c["layer"]:<18} {strat:<14} '
              f'{c["md_n"]:>4} {c["pdf_n"]:>5} {c["md_matched_n"]:>6} {c["canon_rate"]:>6.0%} {consec:<4}')

    # 汇总
    tot = len(comparison)
    if tot:
        print(f'\n{"="*108}')
        print('汇总统计')
        print(f'{"="*108}')

        # 分层小计
        print('\n按层:')
        for layer in ['ch_zh_complete', 'ch_zh_incomplete', 'md_h1_incomplete',
                      'md_h1_complete', 'none_incomplete', 'cn_dun']:
            lc = [c for c in comparison if c['layer'] == layer]
            if not lc:
                print(f'  {layer:<18} 0份可比')
                continue
            avg_md = sum(c['md_n'] for c in lc) / len(lc)
            avg_pdf = sum(c['pdf_n'] for c in lc) / len(lc)
            avg_hit = sum(c['md_matched_n'] for c in lc) / len(lc)
            avg_canon = sum(c['canon_rate'] for c in lc) / len(lc)
            print(f'  {layer:<18} {len(lc)}份: MD均值{avg_md:.1f} PDF均值{avg_pdf:.1f} MD被PDF命中{avg_hit:.1f} 法定章节率{avg_canon:.0%}')

        strat_counts = Counter(c['strategy'] for c in comparison)
        print(f'\n提取策略分布: {dict(strat_counts)}')

        # MD 查全查准粗估 (归一化集合级)
        # PDF 端按法定章节率换算为"可信标题"数
        std_samples = [c for c in comparison if c['strategy'] == 'numbering']
        if std_samples:
            print(f'\n标准格式样本 (编号策略, {len(std_samples)}份):')
            md_tot = sum(c['md_n'] for c in std_samples)
            hit_tot = sum(c['md_matched_n'] for c in std_samples)
            pdf_tot = sum(c['pdf_n'] for c in std_samples)
            print(f'  MD标题总数 {md_tot}, 被PDF命中 {hit_tot} → MD 查准率≈{hit_tot/max(md_tot,1)*100:.1f}%')
            print(f'  PDF标题总数 {pdf_tot}, 法定章节命中数见上 → PDF 纯度={sum(c["canon_rate"] for c in std_samples)/len(std_samples):.1%}')
            consec_n = sum(1 for c in std_samples if c['numbering_consecutive'])
            print(f'  编号连续: {consec_n}/{len(std_samples)}')

        # MD 各层在标准格式下的表现
        print(f'\nMD 通道分层小结 (标准格式 {len(std_samples)} 份):')
        for layer in ['ch_zh_complete', 'ch_zh_incomplete', 'md_h1_incomplete',
                      'md_h1_complete', 'none_incomplete', 'cn_dun']:
            lc = [c for c in std_samples if c['layer'] == layer]
            if not lc:
                continue
            print(f'  {layer:<18} {len(lc)}份: MD命中PDF标题 {sum(c["md_matched_n"] for c in lc)/sum(c["md_n"] for c in lc)*100 if sum(c["md_n"] for c in lc) else 0:.0f}%')

    print(f'\n结果: data/pdf_validation_results.json')
    print(f'对比: data/pdf_vs_md_comparison.json')


if __name__ == '__main__':
    main()
