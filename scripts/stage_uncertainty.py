"""stage_uncertainty.py — 阶段2：不确定性量化（Bootstrap 1000 次 + 分层）

输出 data/uncertainty_report.json 与 deliverables 用的摘要文本。
所有指标基于 annual_semi.h1_fused_result，不引入新的真值假设。
"""
import json
import os
import statistics
from collections import defaultdict

import numpy as np
import psycopg2

PG = dict(host='pg.pro.neuralj.com', dbname='nooshare_dev',
          user='travis', password='sheeta-pg')
N_BOOT = 1000
SEED = 20261114
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'uncertainty_report.json')


def boot_ci(values, fn=np.mean, n_boot=N_BOOT, ci=0.95, rng=None):
    """Bootstrap 百分位置信区间。values 为一维数值序列。"""
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    if len(arr) == 0:
        return None
    rng = rng or np.random.default_rng(SEED)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    est = fn(arr[idx], axis=1)
    lo, hi = np.percentile(est, [(1 - ci) / 2 * 100, (1 + ci) / 2 * 100])
    return dict(n=len(arr), mean=round(float(fn(arr)), 4),
                ci_low=round(float(lo), 4), ci_high=round(float(hi), 4),
                median=round(float(np.median(arr)), 4),
                std=round(float(np.std(arr)), 4))


def boot_prop(flags, n_boot=N_BOOT, ci=0.95, rng=None):
    """比例型指标的 Bootstrap CI（如 ≥0.9 占比）。"""
    arr = np.asarray([1 if f else 0 for f in flags], dtype=float)
    if len(arr) == 0:
        return None
    rng = rng or np.random.default_rng(SEED + 1)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    est = arr[idx].mean(axis=1)
    lo, hi = np.percentile(est, [(1 - ci) / 2 * 100, (1 + ci) / 2 * 100])
    return dict(n=len(arr), rate=round(float(arr.mean()), 4),
                ci_low=round(float(lo), 4), ci_high=round(float(hi), 4))


def main():
    rng = np.random.default_rng(SEED)
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("""SELECT slot_key, stock_code, report_year, period, source,
                          legal_rate, cross_agreement, confidence, pdf_strategy,
                          needs_review, failure_mode, n_headings
                   FROM annual_semi.h1_fused_result""")
    rows = cur.fetchall()
    conn.close()
    print(f'读入 {len(rows)} 条')

    rep = {'n_total': len(rows), 'n_boot': N_BOOT, 'seed': SEED,
           'method': 'bootstrap percentile, 1000 resamples, seed=20261114',
           'sections': {}}

    all_legal = [r[5] for r in rows if r[5] is not None]
    all_cross = [r[6] for r in rows if r[6] is not None]
    rep['sections']['overall'] = {
        'legal_rate': boot_ci(all_legal, rng=rng),
        'legal_rate_ge_0_9': boot_prop([x >= 0.9 for x in all_legal], rng=rng),
        'cross_agreement': boot_ci(all_cross, rng=rng),
        'cross_agreement_ge_0_8': boot_prop([x >= 0.8 for x in all_cross], rng=rng),
        'n_headings': boot_ci([r[11] for r in rows], rng=rng),
    }

    # ---- 按 source 分层 ----
    by_source = defaultdict(list)
    for r in rows:
        by_source[r[4]].append(r)
    rep['sections']['by_source'] = {}
    for src, rs in sorted(by_source.items(), key=lambda x: -len(x[1])):
        lr = [x[5] for x in rs if x[5] is not None]
        rep['sections']['by_source'][src] = {
            'n': len(rs),
            'legal_rate': boot_ci(lr, rng=rng),
            'legal_rate_ge_0_9': boot_prop([x >= 0.9 for x in lr], rng=rng),
            'mean_confidence': round(statistics.mean(x[7] for x in rs), 4),
        }

    # ---- 按 period / year 分层 ----
    for dim, idx in [('by_period', 3), ('by_year', 2)]:
        groups = defaultdict(list)
        for r in rows:
            groups[r[idx]].append(r)
        rep['sections'][dim] = {}
        for k, rs in sorted(groups.items(), key=lambda x: str(x[0])):
            lr = [x[5] for x in rs if x[5] is not None]
            rep['sections'][dim][str(k)] = {
                'n': len(rs),
                'legal_rate': boot_ci(lr, rng=rng),
                'legal_rate_ge_0_9': boot_prop([x >= 0.9 for x in lr], rng=rng),
            }

    # ---- 按 PDF strategy 分层（仅 PDF 参与的样本） ----
    by_st = defaultdict(list)
    for r in rows:
        if r[8]:
            by_st[r[8]].append(r)
    rep['sections']['by_pdf_strategy'] = {}
    for st, rs in sorted(by_st.items(), key=lambda x: -len(x[1])):
        lr = [x[5] for x in rs if x[5] is not None]
        cr = [x[6] for x in rs if x[6] is not None]
        rep['sections']['by_pdf_strategy'][st] = {
            'n': len(rs),
            'legal_rate': boot_ci(lr, rng=rng),
            'cross_agreement': boot_ci(cr, rng=rng),
        }

    # ---- 覆盖率 / 可修复性（比例型 CI） ----
    rep['sections']['coverage'] = {
        'md_complete': boot_prop([r[4] == 'md' for r in rows], rng=rng),
        'pdf_repaired': boot_prop([r[4].startswith('pdf_replace') for r in rows], rng=rng),
        'needs_review': boot_prop([r[9] for r in rows], rng=rng),
        'unrepairable': boot_prop([r[4] == 'unrepairable' for r in rows], rng=rng),
        'legal_ge_0_9': boot_prop([r[5] is not None and r[5] >= 0.9 for r in rows], rng=rng),
    }

    # ---- 未闭环声明 ----
    rep['caveats'] = [
        '金标准人工标注（301份底稿）尚未完成，无法给出独立于全部管线的 P/R/F1',
        '目录页对齐率已废除（与提取结果同源，循环论证）',
        '横截面共识集仅用于离群检测，不是真值',
        'confidence 为启发式赋值，未经标注数据校准',
        '阶段3全量A/B提前终止于批次29（5,764份PDF），未跑完34,044份',
    ]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print(f'写出 {OUT}')

    # ---- 摘要 ----
    print('\n=== 总览（95% CI） ===')
    for k, v in rep['sections']['overall'].items():
        if v:
            print(f'  {k}: {v.get("mean", v.get("rate"))} '
                  f'[{v["ci_low"]}, {v["ci_high"]}] n={v["n"]}')
    print('\n=== 按 source ===')
    for k, v in rep['sections']['by_source'].items():
        lr = v['legal_rate']
        print(f'  {k}: n={v["n"]}, legal={lr["mean"]} [{lr["ci_low"]},{lr["ci_high"]}], '
              f'conf={v["mean_confidence"]}')
    print('\n=== 按 strategy ===')
    for k, v in rep['sections']['by_pdf_strategy'].items():
        lr, cr = v['legal_rate'], v['cross_agreement']
        print(f'  {k}: n={v["n"]}, legal={lr["mean"]}, '
              f'cross={cr["mean"] if cr else "N/A"}')
    print('\n=== 覆盖率 ===')
    for k, v in rep['sections']['coverage'].items():
        print(f'  {k}: {v["rate"]} [{v["ci_low"]},{v["ci_high"]}]')


if __name__ == '__main__':
    main()
