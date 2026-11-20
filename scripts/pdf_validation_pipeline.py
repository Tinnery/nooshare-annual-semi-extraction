"""
PDF 字体指纹通道验证 Pipeline
阶段0: 分层抽样50份 → 巨潮解析直链 → 下载 → 字体指纹提取 → 对比MD通道
"""
import json, os, re, time, sys
import urllib.request, urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

TEMP = os.environ.get('TEMP', r'C:\Users\travis\AppData\Local\Temp')
PDF_DIR = os.path.join(TEMP, 'pdf_validation_samples')
os.makedirs(PDF_DIR, exist_ok=True)

# ── 巨潮 API 工具 ──────────────────────────────────────────────

CNINFO_SEARCH = 'http://www.cninfo.com.cn/new/information/topSearch/detailOfQuery'
CNINFO_ANNOUNCE = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
CNINFO_STATIC = 'http://static.cninfo.com.cn/'

# 期别 → 公告分类
PERIOD_TO_CATEGORY = {
    2: 'category_bndbg_szsh',   # 半年报 (szse); sse 用 category_bndbg_szsh 也要改
    4: 'category_ndbg_szsh',    # 年报
}
PERIOD_TO_CATEGORY_SSE = {
    2: 'category_bndbg_sh',
    4: 'category_ndbg_sh',
}

def get_exchange(code):
    if code.startswith(('000', '002', '003', '300', '301')):
        return 'szse'
    elif code.startswith(('600', '601', '603', '688')):
        return 'sse'
    return 'unknown'

def query_orgid(stock_code):
    """查询 stock_code 的 orgId"""
    data = urllib.parse.urlencode({
        'keyWord': stock_code, 'maxSecNum': 3, 'maxListNum': 3
    }).encode()
    req = urllib.request.Request(CNINFO_SEARCH, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        for item in d.get('keyBoardList', []):
            if item['code'] == stock_code:
                return item['orgId']
    except Exception as e:
        print(f'  orgId查询失败 {stock_code}: {e}')
    return None

def query_pdf_url(stock_code, orgid, report_year, period):
    """查询指定报告的 PDF 下载链接"""
    exchange = get_exchange(stock_code)
    column = 'szse' if exchange == 'szse' else 'sse'
    
    if exchange == 'sse':
        category = PERIOD_TO_CATEGORY_SSE.get(period, 'category_ndbg_sh')
    else:
        category = PERIOD_TO_CATEGORY.get(period, 'category_ndbg_szsh')
    
    # 年报/半年报的标题关键词
    if period == 4:
        title_keywords = ['年度报告']
        title_exclude = ['摘要', '英文', '修订', '更正', '补充', '已取消']
    else:
        title_keywords = ['半年度报告']
        title_exclude = ['摘要', '英文', '修订', '更正', '补充', '已取消']
    
    se_date_start = f'{report_year}-01-01'
    se_date_end = f'{report_year}-12-31'
    
    data = urllib.parse.urlencode({
        'pageNum': 1, 'pageSize': 30, 'column': column, 'tabName': 'fulltext',
        'stock': f'{stock_code},{orgid}', 'searchkey': '', 'secid': '',
        'category': category, 'trade': '',
        'seDate': f'{se_date_start}~{se_date_end}'
    }).encode()
    
    try:
        req = urllib.request.Request(CNINFO_ANNOUNCE, data=data)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        
        anns = d.get('announcements') or []
        for a in anns:
            title = a.get('announcementTitle', '')
            # 检查是否匹配
            if not any(kw in title for kw in title_keywords):
                continue
            if any(ex in title for ex in title_exclude):
                continue
            adjunct = a.get('adjunctUrl', '')
            if adjunct:
                return CNINFO_STATIC + adjunct, title
    except Exception as e:
        print(f'  PDF查询失败 {stock_code} {report_year}-{period}: {e}')
    
    return None, None

def download_pdf(url, stock_code, report_year, period):
    """下载 PDF 到本地"""
    fn = f'{stock_code}_{report_year}_{period}.pdf'
    out_path = os.path.join(PDF_DIR, fn)
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
        return out_path  # 已下载
    try:
        urllib.request.urlretrieve(url, out_path)
        return out_path
    except Exception as e:
        print(f'  下载失败 {fn}: {e}')
        return None

# ── PDF 字体指纹提取 ──────────────────────────────────────────────

def extract_h1_from_pdf(pdf_path):
    """从 PDF 提取一级标题（字体指纹法）"""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    
    doc = fitz.open(pdf_path)
    
    # 1. 先尝试书签
    toc = doc.get_toc()
    lv1_bookmarks = [t for t in toc if t[0] == 1]
    
    # 2. 收集所有行的字体信息
    sec_pat = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]')
    all_lines = []  # (size, font, flags, text, page)
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
    
    # 3. 计算正文主导字号
    if not body_sizes:
        return None, {'error': '无正文行'}
    
    body_main_size = body_sizes.most_common(1)[0][0]
    
    # 4. 找一级标题候选：字号显著大于正文 + 独立成行
    h1_candidates = []
    for size, font, flags, text, page in all_lines:
        # 条件1: 字号比正文大至少 2pt
        if size - body_main_size >= 2.0:
            # 条件2: 匹配"第X节/章"编号
            if sec_pat.match(text) and len(text) < 40:
                h1_candidates.append({
                    'text': text, 'size': size, 'font': font,
                    'flags': flags, 'page': page,
                    'match_type': 'numbering'
                })
    
    # 5. 如果编号匹配太少，放宽到大字号独立行
    if len(h1_candidates) < 5:
        for size, font, flags, text, page in all_lines:
            if size - body_main_size >= 3.0 and len(text) < 50:
                # 排除明显非标题的
                if any(kw in text for kw in ['目录', '释义', '声明', '保证', '真实']):
                    if len(text) > 40:  # 长文本可能是拼接噪声
                        continue
                already = any(c['text'] == text and c['page'] == page for c in h1_candidates)
                if not already:
                    h1_candidates.append({
                        'text': text, 'size': size, 'font': font,
                        'flags': flags, 'page': page,
                        'match_type': 'font_size'
                    })
    
    # 6. 按页码排序
    h1_candidates.sort(key=lambda x: x['page'])
    
    # 7. 构建结果
    result = {
        'body_main_size': body_main_size,
        'n_candidates': len(h1_candidates),
        'has_bookmarks': len(toc) > 0,
        'n_l1_bookmarks': len(lv1_bookmarks),
        'bookmark_titles': [t[1] for t in lv1_bookmarks[:15]],
        'candidates': h1_candidates[:20],
    }
    
    headings = [c['text'] for c in h1_candidates]
    return headings, result

# ── 主流程 ──────────────────────────────────────────────────────

def main():
    # 加载抽样
    with open('data/sample50_for_pdf_validation.json', 'r', encoding='utf-8') as f:
        samples = json.load(f)
    
    print(f'=' * 80)
    print(f'PDF 字体指纹通道验证 Pipeline')
    print(f'=' * 80)
    print(f'抽样数: {len(samples)}')
    print(f'PDF下载目录: {PDF_DIR}')
    
    # Step 1: 查询 orgId（去重）
    unique_codes = list(set(s['stock_code'] for s in samples))
    print(f'\n[Step 1] 查询 {len(unique_codes)} 个 stock_code 的 orgId...')
    orgid_map = {}
    for i, code in enumerate(unique_codes):
        orgid = query_orgid(code)
        if orgid:
            orgid_map[code] = orgid
        if (i + 1) % 10 == 0:
            print(f'  进度: {i+1}/{len(unique_codes)}')
        time.sleep(0.3)  # 限速
    
    print(f'  成功: {len(orgid_map)}/{len(unique_codes)}')
    
    # Step 2: 查询 PDF 直链
    print(f'\n[Step 2] 查询 {len(samples)} 份报告的 PDF 直链...')
    pdf_links = []
    for i, s in enumerate(samples):
        code = s['stock_code']
        orgid = orgid_map.get(code)
        if not orgid:
            pdf_links.append({**s, 'pdf_url': None, 'pdf_title': None, 'status': 'no_orgid'})
            continue
        
        url, title = query_pdf_url(code, orgid, s['report_year'], s['period'])
        if url:
            pdf_links.append({**s, 'pdf_url': url, 'pdf_title': title, 'status': 'found'})
        else:
            pdf_links.append({**s, 'pdf_url': None, 'pdf_title': None, 'status': 'not_found'})
        
        if (i + 1) % 10 == 0:
            print(f'  进度: {i+1}/{len(samples)}')
        time.sleep(0.3)
    
    found = sum(1 for p in pdf_links if p['status'] == 'found')
    print(f'  找到: {found}/{len(samples)}')
    
    # Step 3: 下载 PDF
    print(f'\n[Step 3] 下载 PDF...')
    downloaded = 0
    for i, p in enumerate(pdf_links):
        if p['status'] != 'found':
            continue
        path = download_pdf(p['pdf_url'], p['stock_code'], p['report_year'], p['period'])
        if path:
            p['pdf_path'] = path
            p['status'] = 'downloaded'
            downloaded += 1
        else:
            p['status'] = 'download_failed'
        if (i + 1) % 10 == 0:
            print(f'  进度: {i+1}/{len(pdf_links)}')
    
    print(f'  下载成功: {downloaded}')
    
    # Step 4: 字体指纹提取
    print(f'\n[Step 4] 字体指纹提取...')
    results = []
    for p in pdf_links:
        if p['status'] != 'downloaded':
            results.append({**p, 'pdf_headings': None, 'pdf_meta': None})
            continue
        
        try:
            headings, meta = extract_h1_from_pdf(p['pdf_path'])
            results.append({
                **p, 
                'pdf_headings': headings,
                'pdf_meta': meta,
                'status': 'extracted'
            })
        except Exception as e:
            results.append({
                **p,
                'pdf_headings': None,
                'pdf_meta': {'error': str(e)},
                'status': 'extract_failed'
            })
    
    extracted = sum(1 for r in results if r['status'] == 'extracted')
    print(f'  提取成功: {extracted}')
    
    # Step 5: 保存结果
    with open('data/pdf_validation_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f'\n[Step 5] 结果已保存: data/pdf_validation_results.json')
    
    # Step 6: 输出摘要
    print(f'\n{"=" * 80}')
    print(f'摘要报告')
    print(f'{"=" * 80}')
    
    status_counts = Counter(r['status'] for r in results)
    print(f'\n状态分布:')
    for status, cnt in status_counts.most_common():
        print(f'  {status}: {cnt}')
    
    # 按层统计
    print(f'\n按层统计:')
    for layer in ['ch_zh_complete', 'ch_zh_incomplete', 'md_h1_incomplete', 'md_h1_complete', 'none_incomplete', 'cn_dun']:
        layer_results = [r for r in results if r.get('layer') == layer]
        extracted_cnt = sum(1 for r in layer_results if r['status'] == 'extracted')
        print(f'  {layer}: {len(layer_results)}份, 提取成功 {extracted_cnt}')
    
    # 书签覆盖率
    bookmark_count = sum(1 for r in results if r.get('pdf_meta') and r['pdf_meta'].get('has_bookmarks'))
    total_extracted = sum(1 for r in results if r['status'] == 'extracted')
    print(f'\n书签覆盖率: {bookmark_count}/{total_extracted}')
    
    return results

if __name__ == '__main__':
    main()
