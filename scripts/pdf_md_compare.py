"""
补齐对比数据:
1. 对 22 份 not_found 的报告用关键词检索重试 (category 检索会因板块分类变化而漏)
2. 从 PG 拉取全部 49 份样本的 MD 通道实际一级标题
"""
import json, os, re, time
import urllib.request, urllib.parse
from collections import Counter

TEMP = os.environ.get('TEMP', r'C:\Users\travis\AppData\Local\Temp')
PDF_DIR = os.path.join(TEMP, 'pdf_validation_samples')
os.makedirs(PDF_DIR, exist_ok=True)

CNINFO_SEARCH = 'http://www.cninfo.com.cn/new/information/topSearch/detailOfQuery'
CNINFO_ANNOUNCE = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
CNINFO_STATIC = 'http://static.cninfo.com.cn/'


def get_exchange(code):
    if code.startswith(('000', '002', '003', '300', '301')):
        return 'szse'
    elif code.startswith(('600', '601', '603', '688')):
        return 'sse'
    return 'unknown'


def query_announcements_by_keyword(stock_code, orgid, report_year, period):
    """用空 category + 关键词检索 (更宽松)"""
    exchange = get_exchange(stock_code)
    column = 'szse' if exchange == 'szse' else 'sse'

    # report_year 是报告所属年度; 年报在次年发布, 半年报在当年发布
    if period == 4:
        kw = '年度报告'
        se_start = f'{report_year + 1}-01-01'
        se_end = f'{report_year + 1}-06-30'
    else:
        kw = '半年度报告'
        se_start = f'{report_year}-01-01'
        se_end = f'{report_year}-12-31'

    data = urllib.parse.urlencode({
        'pageNum': 1, 'pageSize': 30, 'column': column, 'tabName': 'fulltext',
        'stock': f'{stock_code},{orgid}', 'searchkey': kw, 'secid': '',
        'category': '', 'trade': '',
        'seDate': f'{se_start}~{se_end}'
    }).encode()

    req = urllib.request.Request(CNINFO_ANNOUNCE, data=data)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())

    anns = d.get('announcements') or []
    exclude = ['摘要', '英文', '已取消', '意见', '提示性']
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


def extract_h1_from_pdf(pdf_path):
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    lv1_bookmarks = [t for t in toc if t[0] == 1]

    sec_pat = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]')
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
        return None, {'error': '无正文行'}

    body_main_size = body_sizes.most_common(1)[0][0]

    h1_candidates = []
    for size, font, flags, text, page in all_lines:
        if size - body_main_size >= 2.0 and sec_pat.match(text) and len(text) < 40:
            h1_candidates.append({'text': text, 'size': size, 'font': font,
                                  'flags': flags, 'page': page, 'match_type': 'numbering'})

    if len(h1_candidates) < 5:
        for size, font, flags, text, page in all_lines:
            if size - body_main_size >= 3.0 and len(text) < 50:
                if len(text) > 40 and any(k in text for k in ['目录', '声明', '保证', '真实']):
                    continue
                already = any(c['text'] == text and c['page'] == page for c in h1_candidates)
                if not already:
                    h1_candidates.append({'text': text, 'size': size, 'font': font,
                                          'flags': flags, 'page': page, 'match_type': 'font_size'})

    h1_candidates.sort(key=lambda x: x['page'])

    meta = {
        'body_main_size': body_main_size,
        'n_candidates': len(h1_candidates),
        'has_bookmarks': len(toc) > 0,
        'n_l1_bookmarks': len(lv1_bookmarks),
    }
    headings = [c['text'] for c in h1_candidates]
    return headings, meta


def fetch_md_headings_pg(samples):
    """从 PG 拉取全部样本的 MD 通道实际一级标题"""
    import psycopg2
    conn = psycopg2.connect(host='pg.pro.neuralj.com', port=5432, dbname='nooshare_dev',
                            user='travis', password='sheeta-pg')
    cur = conn.cursor()

    md_map = {}
    for s in samples:
        key = (s['stock_code'], s['report_year'], s['period'])
        cur.execute("""
            SELECT ordinal, raw_name, canonical_cat
            FROM annual_semi.h1_heading_detail
            WHERE slot_key = %s
            ORDER BY ordinal
        """, (f"{s['stock_code']}_{s['report_year']}_{s['period']}",))
        rows = cur.fetchall()
        md_map[key] = [{'ordinal': r[0], 'raw_name': r[1], 'canonical_cat': r[2]} for r in rows]

    conn.close()
    return md_map


def main():
    with open('data/pdf_validation_results.json', 'r', encoding='utf-8') as f:
        results = json.load(f)

    # ── 1. 重试 not_found ──
    not_found = [r for r in results if r['status'] == 'not_found']
    print(f'重试 {len(not_found)} 份 not_found ...')
    recovered = 0
    for i, r in enumerate(not_found):
        code, year, period = r['stock_code'], r['report_year'], r['period']
        try:
            url, title = query_announcements_by_keyword(code, r['orgid'], year, period)
            if url:
                path = download_pdf(url, code, year, period)
                if path:
                    r['pdf_url'] = url
                    r['pdf_title'] = title
                    r['pdf_path'] = path
                    headings, meta = extract_h1_from_pdf(path)
                    if headings is not None:
                        r['pdf_headings'] = headings
                        r['pdf_meta'] = meta
                        r['status'] = 'extracted'
                        recovered += 1
                    else:
                        r['status'] = 'extract_failed'
                        r['pdf_meta'] = meta
        except Exception as e:
            print(f'  {code} {year}-{period}: {e}')
        time.sleep(0.4)
        if (i + 1) % 8 == 0:
            print(f'  进度 {i+1}/{len(not_found)}')
    print(f'恢复成功: {recovered}/{len(not_found)}')

    # ── 2. PG 拉 MD 通道标题 ──
    print(f'\n从 PG 拉取 MD 通道实际标题...')
    md_map = fetch_md_headings_pg(results)
    n_md = sum(1 for v in md_map.values() if v)
    print(f'  有 MD 标题的样本: {n_md}/{len(results)}')

    for r in results:
        key = (r['stock_code'], r['report_year'], r['period'])
        md_rows = md_map.get(key, [])
        r['md_headings'] = [row['raw_name'] for row in md_rows]
        r['md_canonical'] = [row['canonical_cat'] for row in md_rows]

    # ── 3. 保存 ──
    with open('data/pdf_validation_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # ── 4. 逐份对比 ──
    print(f'\n{"="*110}')
    print(f'PDF 字体指纹通道 vs MD 通道 逐份对比')
    print(f'{"="*110}')
    print(f'{"代码":<8} {"年":<5} {"期":<3} {"层":<18} {"MD#":>4} {"PDF#":>5} {"共":>4} {"仅PDF":>5} {"仅MD":>5} {"书签":<4}')
    print('-' * 110)

    comparison = []
    for r in sorted(results, key=lambda x: (x.get('layer',''), x['stock_code'])):
        if r['status'] != 'extracted':
            continue
        md_h = r.get('md_headings', [])
        pdf_h = r.get('pdf_headings', [])
        md_set, pdf_set = set(md_h), set(pdf_h)
        common, only_pdf, only_md = md_set & pdf_set, pdf_set - md_set, md_set - pdf_set

        comp = {
            'stock_code': r['stock_code'], 'year': r['report_year'], 'period': r['period'],
            'layer': r.get('layer'), 'md_method': r.get('extraction_method'),
            'md_n': len(md_h), 'pdf_n': len(pdf_h),
            'common_n': len(common), 'only_pdf_n': len(only_pdf), 'only_md_n': len(only_md),
            'has_bookmarks': r.get('pdf_meta', {}).get('has_bookmarks', False),
            'body_main_size': r.get('pdf_meta', {}).get('body_main_size'),
            'md_headings': md_h, 'pdf_headings': pdf_h,
            'only_pdf_titles': sorted(only_pdf), 'only_md_titles': sorted(only_md),
        }
        comparison.append(comp)

        bm = 'Y' if comp['has_bookmarks'] else 'N'
        print(f'{comp["stock_code"]:<8} {comp["year"]:<5} {comp["period"]:<3} {comp["layer"]:<18} '
              f'{comp["md_n"]:>4} {comp["pdf_n"]:>5} {comp["common_n"]:>4} {comp["only_pdf_n"]:>5} {comp["only_md_n"]:>5} {bm:<4}')

    # ── 5. 汇总统计 ──
    print(f'\n{"="*110}')
    print('汇总')
    print(f'{"="*110}')
    total = len(comparison)
    status_counts = Counter(r['status'] for r in results)
    print(f'样本状态: {dict(status_counts)}')
    print(f'可比样本 (PDF提取成功): {total}')

    if total:
        pdf_more = sum(1 for c in comparison if c['pdf_n'] > c['md_n'])
        md_more = sum(1 for c in comparison if c['md_n'] > c['pdf_n'])
        equal = sum(1 for c in comparison if c['pdf_n'] == c['md_n'])
        print(f'\n标题数对比: PDF更多 {pdf_more} ({pdf_more/total*100:.0f}%), '
              f'MD更多 {md_more} ({md_more/total*100:.0f}%), 相同 {equal} ({equal/total*100:.0f}%)')

        # 以 PDF 为参照估计 MD 的 P/R (仅基于标题集合重合, 粗略估计)
        tot_common = sum(c['common_n'] for c in comparison)
        tot_md = sum(c['md_n'] for c in comparison)
        tot_pdf = sum(c['pdf_n'] for c in comparison)
        print(f'\n集合级粗估 (以PDF为参照): MD查全率≈{tot_common}/{tot_pdf}={tot_common/max(tot_pdf,1)*100:.1f}%, '
              f'MD查准率≈{tot_common}/{tot_md}={tot_common/max(tot_md,1)*100:.1f}%')

        # 按层
        print(f'\n按层:')
        for layer in ['ch_zh_complete', 'ch_zh_incomplete', 'md_h1_incomplete',
                      'md_h1_complete', 'none_incomplete', 'cn_dun']:
            lc = [c for c in comparison if c['layer'] == layer]
            if not lc:
                print(f'  {layer}: 0份可比')
                continue
            avg_md = sum(c['md_n'] for c in lc) / len(lc)
            avg_pdf = sum(c['pdf_n'] for c in lc) / len(lc)
            avg_common = sum(c['common_n'] for c in lc) / len(lc)
            print(f'  {layer:<18} {len(lc)}份: MD均值{avg_md:.1f}, PDF均值{avg_pdf:.1f}, 共同{avg_common:.1f}')

        # 书签 vs 无书签
        bm = [c for c in comparison if c['has_bookmarks']]
        nbm = [c for c in comparison if not c['has_bookmarks']]
        print(f'\n书签: {len(bm)}份, 无书签: {len(nbm)}份')
        if bm:
            print(f'  有书签 PDF平均标题数: {sum(c["pdf_n"] for c in bm)/len(bm):.1f}')
        if nbm:
            print(f'  无书签 PDF平均标题数: {sum(c["pdf_n"] for c in nbm)/len(nbm):.1f}')

    # 保存对比
    with open('data/pdf_vs_md_comparison.json', 'w', encoding='utf-8') as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f'\n对比明细已保存: data/pdf_vs_md_comparison.json')


if __name__ == '__main__':
    main()
