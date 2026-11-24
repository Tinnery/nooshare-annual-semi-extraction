import os as _runtime_os
_runtime_os.makedirs(".runtime", exist_ok=True)
"""阶段1a: 500份扩量回归验证 — 抽样→巨潮解析直链→并行下载→12核提取→门禁评估

门禁: numbering命中率>=80% 且 法定纯度>=88% (不回退于阶段0的89.5%)
运行: 在 pro 上  ~/repos/nooshare-annual-semi-extraction/.venv/bin/python scripts/stage1a_pipeline.py
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h1_pdf_core import extract_pdf, norm_heading, match_score  # noqa: E402

import psycopg2  # noqa: E402

PG = dict(host='127.0.0.1', port=5432, dbname='nooshare_dev',
          user='travis', password='sheeta-pg')
STAGING = '/source/annual-semi/pdf-staging-1a'
ORG_CACHE = 'data/cninfo_orgid_cache.json'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Content-Type': 'application/x-www-form-urlencoded'}

BANK_CODES = ['000001', '002142', '002936', '002948', '002958', '002966',
              '600000', '600016', '600036', '600919', '600926', '600928',
              '601009', '601077', '601166', '601169', '601229', '601288',
              '601328', '601398', '601658', '601916', '601939', '601963',
              '601988', '601996', '601998']

# (层名, 配额, where片段, 参数, 按期别对半)
LAYERS = [
    ('general_complete', 148,
     "extraction_method='ch_zh' AND is_complete_l1 AND stock_code <> ALL(%s)", [BANK_CODES], True),
    ('y2021_complete', 50,
     "report_year=2021 AND extraction_method='ch_zh' AND is_complete_l1 AND stock_code <> ALL(%s)", [BANK_CODES], False),
    ('ch_zh_incomplete', 80,
     "extraction_method='ch_zh' AND NOT is_complete_l1 AND stock_code <> ALL(%s)", [BANK_CODES], False),
    ('md_h1_incomplete', 90,
     "extraction_method='md_h1' AND NOT is_complete_l1 AND stock_code <> ALL(%s)", [BANK_CODES], False),
    ('md_h1_complete', 10,
     "extraction_method='md_h1' AND is_complete_l1 AND stock_code <> ALL(%s)", [BANK_CODES], False),
    ('none_incomplete', 40,
     "extraction_method='none' AND stock_code <> ALL(%s)", [BANK_CODES], False),
    ('bank_format', 70,
     "stock_code = ANY(%s)", [BANK_CODES], False),
    ('rare_method', 10,
     "extraction_method NOT IN ('ch_zh','md_h1','none')", None, False),
]


def sample_500():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute('SELECT setseed(0.42)')  # 固化随机抽样, 保证重跑同一批样本
    cur.fetchall()
    base = ("SELECT slot_key, stock_code, report_year, period, extraction_method, is_complete_l1 "
            "FROM annual_semi.h1_report_summary "
            "WHERE period IN (2,4) AND report_year BETWEEN 2021 AND 2024 AND ")
    samples, seen = [], set()

    def collect(name, quota, sql, params, split):
        got = 0
        if split:
            per = quota // 2
            chunks = [(f' AND period={p} ORDER BY random() LIMIT {quota}', p) for p in (4, 2)]
        else:
            chunks = [(f' ORDER BY random() LIMIT {quota * 2}', None)]
        for suffix, _p in chunks:
            if got >= quota:
                break
            cur.execute(base + sql + suffix, params)
            for row in cur.fetchall():
                sk = row[0]
                if sk in seen:
                    continue
                seen.add(sk)
                samples.append({'slot_key': sk, 'stock_code': row[1], 'report_year': row[2],
                                'period': row[3], 'extraction_method': row[4],
                                'is_complete_l1': row[5], 'layer': name})
                got += 1
                if got >= quota:
                    break
        print(f'  {name}: {got}/{quota}')

    for name, quota, sql, params, split in LAYERS:
        collect(name, quota, sql, params, split)

    # 重试阶段0的2份 not_found
    cur.execute("SELECT slot_key, stock_code, report_year, period, extraction_method, is_complete_l1 "
                "FROM annual_semi.h1_report_summary WHERE slot_key IN ('603186_2021_2','600520_2021_2')")
    for row in cur.fetchall():
        if row[0] not in seen:
            seen.add(row[0])
            samples.append({'slot_key': row[0], 'stock_code': row[1], 'report_year': row[2],
                            'period': row[3], 'extraction_method': row[4],
                            'is_complete_l1': row[5], 'layer': 'retry_stage0'})
    conn.close()
    print(f'抽样合计: {len(samples)} 份')
    return samples


def fetch_md_headings(samples):
    keys = [s['slot_key'] for s in samples]
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT slot_key, array_agg(raw_name ORDER BY ordinal) "
                "FROM annual_semi.h1_heading_detail WHERE slot_key = ANY(%s) GROUP BY slot_key", (keys,))
    md_map = {r[0]: list(r[1]) for r in cur.fetchall()}
    conn.close()
    for s in samples:
        s['md_headings'] = md_map.get(s['slot_key'], [])
    return samples


def http_post(url, data, timeout=25):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_org_cache():
    if os.path.exists(ORG_CACHE):
        with open(ORG_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def resolve_orgids(codes):
    cache = load_org_cache()
    todo = [c for c in codes if c not in cache]
    print(f'orgId: 缓存{len(codes)-len(todo)}, 待解析{len(todo)}')
    for i, code in enumerate(todo):
        for attempt in range(3):
            try:
                d = http_post('http://www.cninfo.com.cn/new/information/topSearch/detailOfQuery',
                              {'keyWord': code, 'maxSecNum': 3, 'maxListNum': 3})
                hit = [it for it in (d.get('keyBoardList') or []) if it.get('code') == code]
                if hit:
                    cache[code] = hit[0]['orgId']
                else:
                    cache[code] = None
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        else:
            cache[code] = cache.get(code)
        if (i + 1) % 100 == 0:
            print(f'  orgId {i+1}/{len(todo)}')
        time.sleep(0.12)
    with open(ORG_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    return cache


BAD_TITLE_KW = ['摘要', '英文', '取消', '提示性公告', '作废']
TITLE_PAT = {4: re.compile(r'年度报告'), 2: re.compile(r'半年度报告|半年度摘要报告|中期报告')}
CATEGORY = {4: 'category_ndbg_szsh', 2: 'category_bndbg_szsh'}


def query_announcement(sample, org_cache):
    code, year, period = sample['stock_code'], sample['report_year'], sample['period']
    orgid = org_cache.get(code)
    if not orgid:
        return None, 'no_orgid'
    col = 'sse' if code.startswith('6') else 'szse'
    if period == 4:
        sd = f'{year + 1}-01-01~{year + 1}-09-30'
    else:
        sd = f'{year}-06-01~{year}-12-31'
    try:
        d = http_post('http://www.cninfo.com.cn/new/hisAnnouncement/query',
                      {'pageNum': 1, 'pageSize': 30, 'column': col, 'tabName': 'fulltext',
                       'stock': f'{code},{orgid}', 'searchkey': '', 'secid': '',
                       'category': CATEGORY[period], 'trade': '', 'seDate': sd})
    except Exception as e:
        return None, f'http_error:{type(e).__name__}'
    anns = d.get('announcements') or []
    cands = []
    for a in anns:
        t = (a.get('announcementTitle') or '').strip()
        if not TITLE_PAT[period].search(t):
            continue
        if any(k in t for k in BAD_TITLE_KW):
            continue
        cands.append((0 if '更正' in t or '更新' in t else 1, a['adjunctUrl'], t))
    if not cands:
        return None, 'no_pdf'
    cands.sort(key=lambda x: -x[0])
    return cands[0][1], 'ok'


def download_one(args):
    code, year, period, url = args
    out = os.path.join(STAGING, f'{code}_{year}_{period}.pdf')
    if os.path.exists(out) and os.path.getsize(out) > 100_000:
        return out, 'cached'
    full = f'http://static.cninfo.com.cn/{url}'
    for attempt in range(3):
        try:
            req = urllib.request.Request(full, headers={'User-Agent': UA['User-Agent']})
            with urllib.request.urlopen(req, timeout=180) as r, open(out, 'wb') as f:
                f.write(r.read())
            if os.path.getsize(out) > 100_000:
                return out, 'ok'
        except Exception as e:
            err = f'{type(e).__name__}'
            time.sleep(2 * (attempt + 1))
    try:
        os.remove(out)
    except OSError:
        pass
    return None, err


def _work_extract(args):
    slot_key, path = args
    import signal

    def _alarm(sig, frame):
        raise TimeoutError('extract_timeout_90s')

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(90)
    try:
        headings, meta = extract_pdf(path)
        if headings is None:
            return slot_key, {'status': 'extract_error', 'error': (meta or {}).get('error', 'no_headings')}
        return slot_key, {'status': 'ok', 'pdf_headings': headings, 'pdf_meta': meta}
    except Exception as e:
        return slot_key, {'status': 'extract_error', 'error': f'{type(e).__name__}: {e}'}
    finally:
        signal.alarm(0)


def main():
    t0 = time.time()
    os.makedirs(STAGING, exist_ok=True)

    print('== 1. 分层抽样 ==')
    samples = sample_500()
    samples = fetch_md_headings(samples)

    print('== 2. 巨潮解析 ==')
    org_cache = resolve_orgids(sorted({s['stock_code'] for s in samples}))
    for s in samples:
        url, st = query_announcement(s, org_cache)
        s['pdf_url'], s['resolve_status'] = url, st
    n_ok = sum(1 for s in samples if s['resolve_status'] == 'ok')
    print(f'  解析成功: {n_ok}/{len(samples)}')

    print('== 3. 并行下载 ==')
    dl_tasks = [(s['stock_code'], s['report_year'], s['period'], s['pdf_url'])
                for s in samples if s['pdf_url']]
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(download_one, t): t for t in dl_tasks}
        for i, f in enumerate(as_completed(futs), 1):
            path, st = f.result()
            key = f'{futs[f][0]}_{futs[f][1]}_{futs[f][2]}'
            results[key] = (path, st)
            if (i) % 100 == 0:
                print(f'  下载 {i}/{len(dl_tasks)}')
    dl_stat = Counter(st for _, st in results.values())
    print(f'  下载: {dict(dl_stat)}')
    for s in samples:
        key = s['slot_key']
        if key in results and results[key][0]:
            s['pdf_path'] = results[key][0]

    print('== 4. 并行提取 (12核) ==')
    todo = [(s['slot_key'], s['pdf_path']) for s in samples if s.get('pdf_path')]
    extracted = {}
    with Pool(12) as pool:
        for i, (sk, res) in enumerate(pool.imap_unordered(_work_extract, todo, chunksize=4), 1):
            extracted[sk] = res
            if i % 100 == 0:
                print(f'  提取 {i}/{len(todo)}')
    for s in samples:
        s.update(extracted.get(s['slot_key'], {'status': 'no_pdf'}))

    print('== 5. 指标与门禁 ==')
    report = build_metrics(samples)
    report['elapsed_sec'] = round(time.time() - t0, 1)

    with open('data/stage1a_samples.json', 'w', encoding='utf-8') as f:
        json.dump(samples, f, ensure_ascii=False)
    with open('data/stage1a_metrics.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    write_report_md(report)
    print(json.dumps(report['gates'], ensure_ascii=False, indent=2))
    print(f'完成, 用时 {report["elapsed_sec"]}s')


def build_metrics(samples):
    m = {'n_samples': len(samples)}
    m['resolve'] = dict(Counter(s['resolve_status'] for s in samples))
    m['download'] = dict(Counter(s['status'] for s in samples if s.get('pdf_path')) if False else
                         Counter('no_pdf' if not s.get('pdf_path') else 'downloaded' for s in samples))
    ex = [s for s in samples if s.get('status') == 'ok' and s.get('pdf_headings') is not None]
    m['extract_ok'] = len(ex)
    m['extract_err'] = len(samples) - len(ex)
    m['strategy'] = dict(Counter((s.get('pdf_meta') or {}).get('strategy') for s in ex))

    num = [s for s in ex if (s.get('pdf_meta') or {}).get('strategy') == 'numbering']
    m['numbering_hit_rate'] = round(len(num) / max(len(ex), 1), 3)
    m['purity_mean_numbering'] = round(sum(s['pdf_meta']['purity'] for s in num) / max(len(num), 1), 3)
    m['continuous_rate_numbering'] = round(
        sum(1 for s in num if s['pdf_meta']['continuous']) / max(len(num), 1), 3)
    m['era_numbering'] = dict(Counter(s['pdf_meta']['era'] for s in num))
    m['avg_headings_numbering'] = round(sum(len(s['pdf_headings']) for s in num) / max(len(num), 1), 1)

    # MD 对齐 (以 PDF 为参照, 按MD通道分层)
    md_align = {}
    for layer_key in ['general_complete', 'y2021_complete', 'ch_zh_incomplete',
                      'md_h1_incomplete', 'md_h1_complete', 'none_incomplete',
                      'bank_format', 'rare_method', 'retry_stage0']:
        sub = [s for s in num if s['layer'] == layer_key]
        tot = hit = 0
        for s in sub:
            pdf_norms = [norm_heading(h) for h in s['pdf_headings']]
            for raw in s['md_headings']:
                tot += 1
                if any(match_score(raw, pn) for pn in pdf_norms):
                    hit += 1
        if tot:
            md_align[layer_key] = {'md_total': tot, 'md_matched': hit,
                                   'align_rate': round(hit / tot, 3), 'n_samples': len(sub)}
    m['md_alignment_numbering'] = md_align

    m['gates'] = {
        'numbering_hit_ge_80pct': m['numbering_hit_rate'] >= 0.80,
        'purity_ge_88pct': m['purity_mean_numbering'] >= 0.88,
        'pass': m['numbering_hit_rate'] >= 0.80 and m['purity_mean_numbering'] >= 0.88,
    }
    return m


def write_report_md(m):
    lines = [
        '# 阶段1a 扩量回归验证报告',
        '',
        f'- 抽样 {m["n_samples"]} 份 | 解析成功 {m["resolve"].get("ok", 0)} | '
        f'下载成功 {m["download"].get("downloaded", 0)} | 提取成功 {m["extract_ok"]}',
        f'- 用时 {m["elapsed_sec"]}s',
        '',
        '## 策略分布',
        f'```json\n{json.dumps(m["strategy"], ensure_ascii=False)}\n```',
        '',
        '## 门禁',
        f'- numbering 命中率: **{m["numbering_hit_rate"]:.1%}** (门禁 >=80%) → '
        f'{"PASS" if m["gates"]["numbering_hit_ge_80pct"] else "FAIL"}',
        f'- 法定纯度(numbering内均值): **{m["purity_mean_numbering"]:.1%}** (门禁 >=88%) → '
        f'{"PASS" if m["gates"]["purity_ge_88pct"] else "FAIL"}',
        f'- 编号连续率: {m["continuous_rate_numbering"]:.1%} | 平均标题数: {m["avg_headings_numbering"]}',
        f'- 年代分布: {json.dumps(m["era_numbering"], ensure_ascii=False)}',
        '',
        '## 总判定: ' + ('**PASS — 进入阶段1b**' if m['gates']['pass'] else '**FAIL — 停在此阶段修根因**'),
        '',
        '## MD 对齐率 (numbering样本内, 以PDF为参照)',
        '',
        '| 层 | 样本数 | MD标题总数 | 对齐 | 对齐率 |',
        '|---|---|---|---|---|',
    ]
    for k, v in m['md_alignment_numbering'].items():
        lines.append(f'| {k} | {v["n_samples"]} | {v["md_total"]} | {v["md_matched"]} | {v["align_rate"]:.1%} |')
    with open('.runtime/pdf_validation_report_1a.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
