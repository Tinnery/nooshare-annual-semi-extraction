"""stage2_bulk.py — PDF 批量获取+提取+入库（阶段2长尾 / 阶段3全量 共用, 可断点续传）

流程: PG目标清单 → 巨潮解析直链 → 下载到本地tmp → 12核提取 → 结果写PG → PDF上传rustfs → 清理tmp
状态: pdf_acquisition 表记下载状态, h1_pdf_result 表记提取结果; 重跑自动跳过已完成项。

用法:
  H1_SCOPE=longtail .venv/bin/python scripts/stage2_bulk.py          # 阶段2: md_h1/none/不完整存量
  H1_SCOPE=full      .venv/bin/python scripts/stage2_bulk.py          # 阶段3: 全部36,806
  H1_SCOPE=longtail ... scripts/stage2_bulk.py --report-only         # 只出报告不动网络
"""
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h1_pdf_core import extract_pdf, match_score, norm_heading  # noqa: E402

import psycopg2  # noqa: E402

PG = dict(host='127.0.0.1', port=5432, dbname='nooshare_dev', user='travis', password='sheeta-pg')
SCOPE = os.environ.get('H1_SCOPE', 'longtail')
TMP = os.environ.get('H1_PDF_TMP', '/source/annual-semi/pdf-tmp')
ORG_CACHE = 'data/cninfo_orgid_cache.json'
BATCH = int(os.environ.get('H1_BATCH', '200'))
REPORT_MD = 'data/pdf_validation_report_2.md' if SCOPE == 'longtail' else 'data/pdf_validation_report_3.md'
REPORT_JSON = 'data/stage2_metrics.json' if SCOPE == 'longtail' else 'data/stage3_metrics.json'

RUSTFS = {'endpoint': 'https://s3.rustfs.pro.neuralj.com', 'key': os.environ.get("RUSTFS_ACCESS_KEY", ""),
          'secret': os.environ.get("RUSTFS_SECRET_KEY", ""), 'bucket': 'annual-semi'}

DDL = [
    """CREATE TABLE IF NOT EXISTS annual_semi.pdf_acquisition(
        slot_key text PRIMARY KEY, stock_code text, report_year int, period int,
        adjunct_url text, status text, bytes bigint, error text,
        updated_at timestamptz DEFAULT now())""",
    """CREATE TABLE IF NOT EXISTS annual_semi.h1_pdf_result(
        slot_key text PRIMARY KEY, stock_code text, report_year int, period int,
        headings jsonb, n_headings int, strategy text, purity real, continuous boolean,
        era text, toc_headings jsonb, extracted_at timestamptz DEFAULT now())""",
]


def pg_conn():
    return psycopg2.connect(**PG)


def http_post(url, data, timeout=25, ua=None):
    import urllib.request
    import urllib.parse
    headers = ua or {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                     'Content-Type': 'application/x-www-form-urlencoded'}
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def resolve_orgids(codes):
    """带缓存的 orgId 解析 (与阶段1a同一缓存文件)"""
    cache = {}
    if os.path.exists(ORG_CACHE):
        with open(ORG_CACHE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
    todo = [c for c in codes if c not in cache]
    print(f'orgId: 缓存 {len(codes) - len(todo)}, 待解析 {len(todo)}', flush=True)
    for i, code in enumerate(todo):
        for attempt in range(3):
            try:
                d = http_post('http://www.cninfo.com.cn/new/information/topSearch/detailOfQuery',
                              {'keyWord': code, 'maxSecNum': 3, 'maxListNum': 3})
                hit = [it for it in (d.get('keyBoardList') or []) if it.get('code') == code]
                cache[code] = hit[0]['orgId'] if hit else None
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        else:
            cache.setdefault(code, None)
        if (i + 1) % 200 == 0:
            print(f'  orgId {i + 1}/{len(todo)}', flush=True)
        time.sleep(0.12)
    with open(ORG_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    return cache


import re  # noqa: E402

TITLE_PAT = {4: re.compile(r'年度报告'), 2: re.compile(r'半年度报告|中期报告')}
CATEGORY = {4: 'category_ndbg_szsh', 2: 'category_bndbg_szsh'}
BAD_TITLE_KW = ['摘要', '英文', '取消', '提示性公告', '作废']


def query_url(code, year, period, org_cache):
    orgid = org_cache.get(code)
    if not orgid:
        return None, 'no_orgid'
    col = 'sse' if code.startswith('6') else 'szse'
    sd = f'{year + 1}-01-01~{year + 1}-09-30' if period == 4 else f'{year}-06-01~{year}-12-31'
    try:
        d = http_post('http://www.cninfo.com.cn/new/hisAnnouncement/query',
                      {'pageNum': 1, 'pageSize': 30, 'column': col, 'tabName': 'fulltext',
                       'stock': f'{code},{orgid}', 'searchkey': '', 'secid': '',
                       'category': CATEGORY[period], 'trade': '', 'seDate': sd})
    except Exception as e:
        return None, f'http_error:{type(e).__name__}'
    cands = []
    for a in (d.get('announcements') or []):
        t = (a.get('announcementTitle') or '').strip()
        if not TITLE_PAT[period].search(t) or any(k in t for k in BAD_TITLE_KW):
            continue
        cands.append((0 if ('更正' in t or '更新' in t) else 1, a['adjunctUrl']))
    if not cands:
        return None, 'no_pdf'
    cands.sort(key=lambda x: -x[0])
    return cands[0][1], 'ok'


def download_one(args):
    """下载到本地tmp; 返回 (slot_key, path, status, bytes, error)"""
    import urllib.request
    slot_key, code, year, period, url = args
    out = os.path.join(TMP, f'{code}_{year}_{period}.pdf')
    if os.path.exists(out) and os.path.getsize(out) > 100_000:
        return slot_key, out, 'ok', os.path.getsize(out), None
    full = f'http://static.cninfo.com.cn/{url}'
    err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(full, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=180) as r, open(out, 'wb') as f:
                f.write(r.read())
            sz = os.path.getsize(out)
            if sz > 100_000:
                return slot_key, out, 'ok', sz, None
            err = 'too_small'
        except Exception as e:
            err = f'{type(e).__name__}'
            time.sleep(2 * (attempt + 1))
    try:
        os.remove(out)
    except OSError:
        pass
    return slot_key, None, 'download_error', 0, err


def _work_extract(args):
    slot_key, code, year, period, path = args
    import signal

    def _alarm(sig, frame):
        raise TimeoutError('extract_timeout_90s')

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(90)
    try:
        headings, meta = extract_pdf(path)
    except Exception:
        headings, meta = None, {'error': 'extract_error_or_timeout'}
    finally:
        signal.alarm(0)
    if headings is None:
        return slot_key, (code, year, period, None, None)
    return slot_key, (code, year, period, headings, meta)


def upload_rustfs(local_path, key):
    try:
        import boto3
        import urllib3
        from botocore.config import Config
        urllib3.disable_warnings()
        client = boto3.client('s3', endpoint_url=RUSTFS['endpoint'],
                              aws_access_key_id=RUSTFS['key'], aws_secret_access_key=RUSTFS['secret'],
                              verify=False,
                              config=Config(signature_version='s3v4',
                                            s3={'addressing_style': 'path'}, max_pool_connections=32))
        client.upload_file(local_path, RUSTFS['bucket'], key)
        return True
    except Exception as e:
        print(f'  rustfs upload failed {key}: {type(e).__name__}', flush=True)
        return False


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def upsert_acquisition(cur, rows):
    for r in rows:
        cur.execute("""INSERT INTO annual_semi.pdf_acquisition
            (slot_key, stock_code, report_year, period, adjunct_url, status, bytes, error)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (slot_key) DO UPDATE SET status=EXCLUDED.status, bytes=EXCLUDED.bytes,
              error=EXCLUDED.error, adjunct_url=EXCLUDED.adjunct_url, updated_at=now()""", r)


def upsert_results(cur, rows):
    for r in rows:
        cur.execute("""INSERT INTO annual_semi.h1_pdf_result
            (slot_key, stock_code, report_year, period, headings, n_headings, strategy,
             purity, continuous, era, toc_headings)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (slot_key) DO UPDATE SET headings=EXCLUDED.headings,
              n_headings=EXCLUDED.n_headings, strategy=EXCLUDED.strategy, purity=EXCLUDED.purity,
              continuous=EXCLUDED.continuous, era=EXCLUDED.era,
              toc_headings=EXCLUDED.toc_headings, extracted_at=now()""", r)


def run_pipeline():
    conn = pg_conn()
    cur = conn.cursor()
    for ddl in DDL:
        cur.execute(ddl)
    conn.commit()

    if SCOPE == 'longtail':
        cur.execute("""SELECT slot_key, stock_code, report_year, period, extraction_method, is_complete_l1
            FROM annual_semi.h1_report_summary
            WHERE period IN (2,4) AND report_year BETWEEN 2021 AND 2024
              AND (extraction_method IN ('md_h1','none') OR NOT is_complete_l1)
            ORDER BY report_year, period, stock_code""")
    else:
        cur.execute("""SELECT slot_key, stock_code, report_year, period, extraction_method, is_complete_l1
            FROM annual_semi.h1_report_summary
            WHERE period IN (2,4) AND report_year BETWEEN 2021 AND 2024
            ORDER BY report_year, period, stock_code""")
    targets = cur.fetchall()
    print(f'[{SCOPE}] 目标 {len(targets)} 份', flush=True)

    # 已完成集合: 有提取结果的 / 确定性失败(no_orgid, no_pdf)
    cur.execute("SELECT slot_key FROM annual_semi.h1_pdf_result")
    done = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT slot_key, status FROM annual_semi.pdf_acquisition "
                "WHERE status IN ('no_orgid','no_pdf')")
    det_fail = {r[0] for r in cur.fetchall()}
    conn.close()

    todo = [t for t in targets if t[0] not in done and t[0] not in det_fail]
    print(f'待处理 {len(todo)} (已完成 {len(done & {t[0] for t in targets})}, '
          f'确定性失败 {len(det_fail & {t[0] for t in targets})})', flush=True)

    os.makedirs(TMP, exist_ok=True)
    org_cache = {}
    if os.path.exists(ORG_CACHE):
        with open(ORG_CACHE, 'r', encoding='utf-8') as f:
            org_cache = json.load(f)

    t0 = time.time()
    cum = Counter()
    for bi, batch in enumerate(chunks(todo, BATCH), 1):
        bt0 = time.time()
        slots = [b[0] for b in batch]
        codes = sorted({b[1] for b in batch})
        need = [c for c in codes if c not in org_cache]
        if need:
            org_cache.update(resolve_orgids(need))

        # 1) 解析直链
        jobs, acq_rows = [], []
        slot_meta = {}
        for sk, code, year, period, method, complete in batch:
            slot_meta[sk] = (code, year, period)
            url, st = query_url(code, year, period, org_cache)
            if url:
                jobs.append((sk, code, year, period, url))
                acq_rows.append((sk, code, year, period, url, 'ok', None, None))
            else:
                acq_rows.append((sk, code, year, period, None, st, None, st))
                cum[st] += 1

        # 2) 并行下载
        dl_ok = []
        acq_by_slot = {r[0]: list(r) for r in acq_rows}
        if jobs:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = [pool.submit(download_one, j) for j in jobs]
                for f in as_completed(futs):
                    sk, path, st, sz, err = f.result()
                    if sk in acq_by_slot:
                        acq_by_slot[sk][5] = st
                        acq_by_slot[sk][6] = sz
                        acq_by_slot[sk][7] = err
                    if path:
                        dl_ok.append((sk, path))
                    cum[st] += 1
        acq_rows = [tuple(v) for v in acq_by_slot.values()]

        # 3) 提取 (12核)
        ex_rows = []
        if dl_ok:
            tasks = [(sk, *slot_meta[sk], path) for sk, path in dl_ok]
            with Pool(12) as pool:
                for sk, (code, year, period, headings, meta) in pool.imap_unordered(
                        _work_extract, tasks, chunksize=4):
                    if headings is not None:
                        ex_rows.append((sk, code, year, period,
                                        json.dumps(headings, ensure_ascii=False), len(headings),
                                        meta.get('strategy'), meta.get('purity'),
                                        bool(meta.get('continuous')), meta.get('era'),
                                        json.dumps(meta.get('toc_headings') or [], ensure_ascii=False)))
                        cum['extract_ok'] += 1
                    else:
                        cum['extract_fail'] += 1

        # 4) 上传 rustfs + 清理tmp
        up_n = 0
        for sk, path in dl_ok:
            code = slot_meta[sk][0]
            key = f'pdf/{code}/{sk}.pdf'
            if upload_rustfs(path, key):
                up_n += 1
            try:
                os.remove(path)
            except OSError:
                pass
        cum['uploaded'] += up_n

        # 5) 入库
        conn = pg_conn()
        cur = conn.cursor()
        upsert_acquisition(cur, acq_rows)
        if ex_rows:
            upsert_results(cur, ex_rows)
        conn.commit()
        conn.close()

        print(f'批次 {bi}: 解析{len(jobs)} 下载{len(dl_ok)} 提取{len(ex_rows)} 上传{up_n} '
              f'| 累计 {dict(cum)} | 用时 {time.time() - bt0:.0f}s', flush=True)

    print(f'全部完成, 总用时 {(time.time() - t0) / 60:.1f} 分钟, {dict(cum)}', flush=True)


def report_only():
    """从 PG 汇总报告, 不访问网络"""
    conn = pg_conn()
    cur = conn.cursor()
    cur.execute("SELECT strategy, count(*) FROM annual_semi.h1_pdf_result GROUP BY strategy")
    strategies = dict(cur.fetchall())
    cur.execute("SELECT count(*) FROM annual_semi.pdf_acquisition WHERE status IN ('no_orgid','no_pdf')")
    det_fail = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM annual_semi.pdf_acquisition WHERE status NOT IN ('ok','no_orgid','no_pdf')")
    transient_fail = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM annual_semi.h1_pdf_result
                   WHERE strategy='numbering' AND continuous AND n_headings >= 8""")
    strict_complete = cur.fetchone()[0]
    cur.execute("SELECT slot_key, headings FROM annual_semi.h1_pdf_result")
    head_map = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("""SELECT r.slot_key, h.raw_name FROM annual_semi.h1_pdf_result r
                   JOIN annual_semi.h1_heading_detail h ON h.slot_key = r.slot_key""")
    md_map = {}
    for sk, raw in cur.fetchall():
        md_map.setdefault(sk, []).append(raw)
    conn.close()

    md_align_tot = md_align_hit = 0
    for sk, raws in md_map.items():
        if sk not in head_map:
            continue
        pdf_norms = [norm_heading(h) for h in head_map[sk]]
        for raw in raws:
            md_align_tot += 1
            if any(match_score(raw, pn) for pn in pdf_norms if pn):
                md_align_hit += 1

    m = {'scope': SCOPE, 'strategies': strategies, 'deterministic_fail': det_fail,
         'transient_fail': transient_fail, 'strict_complete': strict_complete,
         'n_results': sum(strategies.values()),
         'md_align_rate_all': round(md_align_hit / max(md_align_tot, 1), 3)}
    with open(REPORT_JSON.replace('.json', '_report.json'), 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    print(json.dumps(m, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if '--report-only' in sys.argv:
        report_only()
    else:
        run_pipeline()
