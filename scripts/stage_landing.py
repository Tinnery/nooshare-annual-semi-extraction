"""stage_landing.py — 施工手册 v1.1 落地：多通道融合 + 外部证据 + 故障归因

用法（pro 主机）:
    .venv/bin/python scripts/stage_landing.py              # 全量落地
    .venv/bin/python scripts/stage_landing.py --dry-run    # 只统计不写库

设计要点（相对 v1.0 的修正）:
1. 法定基准 = 证监会公告〔2021〕15/16 号正文十节（不是 11 项模板）
2. 第一节别名集合（"释义" 占 38.7%，严格匹配会误杀）
3. era 由外部元数据 (report_year, period) 决定，不从内容反推
4. toc_headings 不作外部锚点（与 headings 同源，循环论证）
5. 每条结果落库携带证据字段，可回溯
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h1_pdf_core import norm_heading, match_score, _canon_match  # noqa: E402

PG = dict(host='pg.pro.neuralj.com', dbname='nooshare_dev',
          user='travis', password='sheeta-pg')

# ---- 法规基准（外部、独立、已核实） ----
LEGAL_10 = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析', '公司治理',
    '环境和社会责任', '重要事项', '股份变动及股东情况', '优先股相关情况',
    '债券相关情况', '财务报告',
]
FIRST_ALIASES = ['重要提示、目录和释义', '释义', '重要提示及目录',
                 '重要提示和释义', '重要提示、目录、释义', '重要提示']

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS annual_semi.h1_fused_result (
    slot_key            text PRIMARY KEY,
    stock_code          text,
    report_year         integer,
    period              integer,
    source              text NOT NULL,
    final_headings      jsonb NOT NULL,
    n_headings          integer,
    confidence          real,
    legal_rate          real,
    cross_agreement     real,
    consensus_deviation real,
    md_complete         boolean,
    pdf_strategy        text,
    pdf_purity          real,
    evidence            jsonb,
    failure_mode        text,
    needs_review        boolean,
    created_at          timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_h1_fused_source ON annual_semi.h1_fused_result(source);
CREATE INDEX IF NOT EXISTS idx_h1_fused_review ON annual_semi.h1_fused_result(needs_review)
    WHERE needs_review;
"""


def legal_rate(headings):
    """法规十节符合率（外部锚点）。第一节允许别名。"""
    norms = [norm_heading(h) for h in headings if norm_heading(h)]
    if not norms:
        return 0.0
    rest = LEGAL_10[1:]
    hit_rest = sum(1 for c in rest if any(_canon_match(c, pn) for pn in norms))
    first_ok = any(any(_canon_match(a, pn) for pn in norms) for a in FIRST_ALIASES)
    return (hit_rest + (1 if first_ok else 0)) / 10.0


def cross_agreement(md_norms, pdf_norms):
    """MD↔PDF 双向覆盖率均值（两条独立生成链）。无对照返回 None。"""
    if not md_norms or not pdf_norms:
        return None
    a = sum(1 for m in md_norms
            if any(match_score(m, p) or match_score(p, m) for p in pdf_norms)) / len(md_norms)
    b = sum(1 for p in pdf_norms
            if any(match_score(p, m) or match_score(m, p) for m in md_norms)) / len(pdf_norms)
    return (a + b) / 2


def build_consensus(rows):
    """同期横截面众数集：仅用于离群检测，不是真值。"""
    groups = defaultdict(list)
    for slot, hs, year, period in rows:
        groups[(year, period)].append((slot, frozenset(norm_heading(h) for h in hs if norm_heading(h))))
    modal = {}
    for key, items in groups.items():
        if len(items) < 30:
            continue
        freq = Counter(h for _, s in items for h in s)
        modal[key] = {h for h, c in freq.items() if c / len(items) >= 0.8}
    return modal


def consensus_deviation(headings, modal_set):
    """偏离度 = 1 - 命中众数集的比例。众数集不可用时返回 None。"""
    if not modal_set:
        return None
    norms = set(norm_heading(h) for h in headings if norm_heading(h))
    if not norms:
        return 1.0
    return round(1 - len(norms & modal_set) / len(norms), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()

    # ---- 读取三源 ----
    print('读取 MD summary ...', flush=True)
    cur.execute("""SELECT slot_key, stock_code, report_year, period, is_complete_l1,
                          n_headings, template_compliance, normalization_status
                   FROM annual_semi.h1_report_summary""")
    summary = {}
    for sk, code, yr, pd, complete, nh, tc, ns in cur.fetchall():
        summary[sk] = dict(code=code, year=yr, period=pd, complete=bool(complete),
                           n_headings=nh, compliance=tc, norm_status=ns)
    print(f'  {len(summary)} 条')

    print('读取 MD heading detail ...', flush=True)
    cur.execute('SELECT slot_key, canonical_name, raw_name FROM annual_semi.h1_heading_detail')
    md_heads = defaultdict(list)
    for sk, canon, raw in cur.fetchall():
        name = canon or raw
        if name:
            md_heads[sk].append(name)
    print(f'  {len(md_heads)} 个 slot')

    print('读取 PDF 结果 ...', flush=True)
    cur.execute("""SELECT slot_key, headings, n_headings, strategy, purity, continuous, era
                   FROM annual_semi.h1_pdf_result""")
    pdf = {}
    for sk, hs, nh, st, pu, co, era in cur.fetchall():
        pdf[sk] = dict(headings=hs or [], n=nh, strategy=st, purity=pu,
                       continuous=co, era=era)
    print(f'  {len(pdf)} 条')

    cur.execute("SELECT slot_key, status, error FROM annual_semi.pdf_acquisition")
    acq = {sk: (st, err) for sk, st, err in cur.fetchall()}
    print(f'  pdf_acquisition: {len(acq)} 条')

    # ---- 横截面共识（用 PDF 高纯度样本建，避免噪声污染） ----
    print('构建同期共识集 ...', flush=True)
    consensus_rows = [(sk, p['headings'], summary[sk]['year'], summary[sk]['period'])
                      for sk, p in pdf.items()
                      if sk in summary and p['purity'] and p['purity'] >= 0.8
                      and p['strategy'] == 'numbering' and p['headings']]
    modal = build_consensus(consensus_rows)
    print(f'  {len(modal)} 组可用共识集')

    # ---- 逐份决策 ----
    print('逐份融合决策 ...', flush=True)
    out = []
    stats = Counter()
    for sk, s in summary.items():
        md_list = md_heads.get(sk, [])
        md_n = [norm_heading(h) for h in md_list if norm_heading(h)]
        p = pdf.get(sk)
        pdf_list = p['headings'] if p else []
        pdf_n = [norm_heading(h) for h in pdf_list if norm_heading(h)]

        lrate_md = legal_rate(md_list)
        lrate_pdf = legal_rate(pdf_list) if p else None
        cross = cross_agreement(md_n, pdf_n)
        modal_set = modal.get((s['year'], s['period']))
        dev = consensus_deviation(pdf_list or md_list, modal_set)

        acq_status = acq.get(sk, (None, None))[0]

        # 决策树（v1.1 修正）
        # 关键：MD 不完整时，MD 通道本身是残片/噪声，跨管线一致性不具判据资格
        # （实测 736 份 cross<0.6 但 legal>=0.9，恰是修复最成功的案例，
        #   v1.0 误用 cross 门槛把它们判成低置信）
        if s['complete']:
            # MD 完整：以 MD 为主，PDF 作为独立生成链的交叉校验
            source = 'md'
            final = md_list
            legal = lrate_md
            conf = 0.95 if legal >= 0.9 else 0.80
            review = legal < 0.8
            failure = 'md_legal_noncompliance' if review else None
            if cross is not None and cross < 0.5:
                failure = 'cross_pipeline_disagreement_low'
                review = True
        elif p and pdf_n:
            # MD 不完整：判据 = 法规符合率(外部) + PDF 自身质量(编号连续/策略)
            lrate = lrate_pdf or 0.0
            continuous = p['continuous'] is True
            strong_strategy = p['strategy'] == 'numbering'
            final = pdf_list
            legal = lrate
            if lrate >= 0.9 and continuous and strong_strategy:
                source = 'pdf_replace'
                conf = 0.92
                review = False
                failure = None
            elif lrate >= 0.9 and (continuous or strong_strategy):
                source = 'pdf_replace_review'
                conf = 0.82
                review = True
                failure = 'pdf_quality_partial'
            elif lrate >= 0.9:
                source = 'pdf_low_conf'
                conf = 0.70
                review = True
                failure = 'pdf_quality_weak'
            else:
                source = 'pdf_low_conf'
                conf = 0.65
                review = True
                failure = 'legal_noncompliance'
        else:
            source = 'unrepairable'
            final = md_list
            conf = 0.50
            legal = lrate_md
            review = True
            # acq.status 实际取值仅 'ok' / 'no_pdf'，不是旧代码假设的 'uploaded'
            if acq_status == 'no_pdf':
                failure = 'no_pdf:not_found'          # 巨潮侧确实没有该报告
            elif acq_status == 'ok':
                failure = 'pdf_extraction_failed'     # PDF 已下载但没产出标题
            elif not p and acq_status is None:
                failure = 'no_pdf:not_acquired'       # 从未进入采集队列
            else:
                failure = f'no_pdf:{acq_status}'

        stats[source] += 1
        if failure:
            stats[f'fail:{failure.split(":")[0]}'] += 1

        evidence = {
            'legal_base': 'CSRC-2021-15/16-art2-10sections',
            'first_alias_allowed': True,
            'md_n': len(md_n), 'pdf_n': len(pdf_n),
            'md_legal_rate': round(lrate_md, 3),
            'pdf_legal_rate': round(lrate_pdf, 3) if lrate_pdf is not None else None,
            'pdf_continuous': p['continuous'] if p else None,
            'acq_status': acq_status,
            'toc_used_as_external_anchor': False,
        }
        out.append((
            sk, s['code'], s['year'], s['period'], source,
            json.dumps(final, ensure_ascii=False), len(final),
            round(conf, 3), round(legal, 3),
            round(cross, 3) if cross is not None else None,
            dev, s['complete'],
            p['strategy'] if p else None,
            p['purity'] if p else None,
            json.dumps(evidence, ensure_ascii=False),
            failure, bool(review),
        ))

    print('\n=== 决策分布 ===')
    for k, v in stats.most_common():
        print(f'  {k}: {v}')

    lrates = [r[8] for r in out if r[8] is not None]
    crosses = [r[9] for r in out if r[9] is not None]
    print(f'\n法定符合率均值: {sum(lrates)/len(lrates):.4f} (n={len(lrates)})')
    if crosses:
        print(f'跨管线一致性均值: {sum(crosses)/len(crosses):.4f} (n={len(crosses)})')

    if args.dry_run:
        print('\n[dry-run] 未写库')
        conn.close()
        return

    print('\n写入 PG ...', flush=True)
    cur.execute(TABLE_DDL)
    cur.execute('TRUNCATE annual_semi.h1_fused_result')
    cols = ['slot_key', 'stock_code', 'report_year', 'period', 'source',
            'final_headings', 'n_headings', 'confidence', 'legal_rate',
            'cross_agreement', 'consensus_deviation', 'md_complete',
            'pdf_strategy', 'pdf_purity', 'evidence', 'failure_mode', 'needs_review']
    sql = f"INSERT INTO annual_semi.h1_fused_result ({','.join(cols)}) VALUES %s"
    execute_values(cur, sql, out, page_size=1000)
    conn.commit()
    print(f'  写入 {len(out)} 条')
    conn.close()


if __name__ == '__main__':
    main()
