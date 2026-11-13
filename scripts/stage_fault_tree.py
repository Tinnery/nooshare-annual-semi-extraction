"""stage_fault_tree.py — 阶段3：故障模式树与根因归因

对每个 needs_review / low-conf 样本给出：根因分类、可修复性、修复路径。
输出 data/fault_tree.json + data/fault_cases.csv（可复核清单）。
"""
import csv
import json
import os
from collections import Counter, defaultdict

import psycopg2

PG = dict(host='pg.pro.neuralj.com', dbname='nooshare_dev',
          user='travis', password='sheeta-pg')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')

# 故障模式树：叶子 = 根因，value = (分类, 可修复性, 修复路径)
TREE = {
    'no_pdf:not_acquired': ('数据缺失', '可修复', '补跑巨潮解析+下载（阶段2脚本续传）'),
    'no_pdf:not_found': ('数据缺失', '难修复', '巨潮侧无此报告；尝试备用源或标记永久缺失'),
    'no_pdf:download_fail': ('数据缺失', '可修复', '重试下载，检查 URL 时效'),
    'pdf_extraction_failed': ('数据缺失', '可修复', 'PDF 已下载但无标题产出：重试解析；扫描件走 OCR'),
    'legal_noncompliance': ('版式异常', '部分可修复', '专项模板：H股版式/银行版式/编号不连续'),
    'md_legal_noncompliance': ('版式异常', '部分可修复', 'MD 通道法定符合率低：用 PDF 通道复核或专项模板'),
    'pdf_quality_weak': ('算法边界', '可修复', '放宽编号连续性校验或改用目录页结构'),
    'pdf_quality_partial': ('算法边界', '可修复', '人工复核后升级为 pdf_replace'),
    'cross_pipeline_disagreement_low': ('跨源冲突', '需人工', '三源并排底稿人工裁定'),
}

# 按 failure_mode 前缀兜底
def classify(fm):
    if not fm:
        return None
    if fm in TREE:
        return TREE[fm]
    if fm.startswith('no_pdf:'):
        st = fm.split(':', 1)[1]
        if st in ('not_acquired', 'not_found'):
            return TREE.get(f'no_pdf:{st}', ('数据缺失', '难修复', '补采或确认下架'))
        return ('数据缺失', '可修复', f'针对 acq_status={st} 重试')
    return ('未分类', '待分析', '需人工查看')


def main():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("""SELECT slot_key, stock_code, report_year, period, source,
                          legal_rate, cross_agreement, pdf_strategy, pdf_purity,
                          failure_mode, needs_review, n_headings, md_complete,
                          final_headings
                   FROM annual_semi.h1_fused_result""")
    rows = cur.fetchall()

    # 需要归因的：needs_review 或低置信或非 md 主通道
    flagged = [r for r in rows if r[10] or r[4] in ('pdf_low_conf', 'unrepairable')]
    print(f'总记录 {len(rows)}, 需归因 {len(flagged)}')

    by_root = Counter()
    by_category = Counter()
    by_fixability = Counter()
    by_year_period = defaultdict(Counter)
    by_strategy = Counter()

    cases = []
    for r in flagged:
        sk, code, yr, pd, src, lr, cr, st, pu, fm, rv, nh, mdc, fh = r
        info = classify(fm)
        cat, fix, path = info if info else ('无故障', '-', '-')
        root = fm or 'none'
        by_root[root] += 1
        by_category[cat] += 1
        by_fixability[fix] += 1
        by_year_period[(yr, pd)][cat] += 1
        if st:
            by_strategy[(st, cat)] += 1
        cases.append(dict(slot_key=sk, stock_code=code, report_year=yr, period=pd,
                          source=src, legal_rate=lr, cross_agreement=cr,
                          pdf_strategy=st, pdf_purity=pu, failure_mode=root,
                          category=cat, fixability=fix, fix_path=path,
                          n_headings=nh, md_complete=mdc))

    tree = {
        'n_total': len(rows), 'n_flagged': len(flagged),
        'flagged_rate': round(len(flagged) / len(rows), 4),
        'by_root_cause': dict(by_root.most_common()),
        'by_category': dict(by_category.most_common()),
        'by_fixability': dict(by_fixability.most_common()),
        'leaves': [
            {'root': k, 'n': v, 'category': classify(k)[0],
             'fixability': classify(k)[1], 'fix_path': classify(k)[2]}
            for k, v in by_root.most_common()
        ],
        'by_year_period': {f'{k[0]}_P{k[1]}': dict(v) for k, v in sorted(by_year_period.items())},
        'by_strategy': {f'{k[0]}|{k[1]}': v for k, v in by_strategy.most_common()},
    }

    with open(os.path.join(DATA, 'fault_tree.json'), 'w', encoding='utf-8') as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)

    with open(os.path.join(DATA, 'fault_cases.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(cases[0].keys()) if cases else ['slot_key'])
        w.writeheader()
        w.writerows(cases)

    print('\n=== 根因分布 ===')
    for k, v in by_root.most_common():
        c = classify(k)
        print(f'  {k}: {v}  [{c[0]} / {c[1]}]')
    print('\n=== 分类汇总 ===')
    for k, v in by_category.most_common():
        print(f'  {k}: {v}')
    print('\n=== 可修复性 ===')
    for k, v in by_fixability.most_common():
        print(f'  {k}: {v}')
    print('\n=== 按年份期别（前8） ===')
    for k, v in sorted(by_year_period.items())[:8]:
        print(f'  {k[0]} P{k[1]}: {dict(v)}')

    # 边界案例覆盖率：按施工手册定义，以 PDF strategy 非 numbering 为代理
    cur.execute("""SELECT pdf_strategy, COUNT(*) FROM annual_semi.h1_fused_result
                   WHERE pdf_strategy IS NOT NULL GROUP BY 1""")
    st_dist = dict(cur.fetchall())
    print('\n=== 策略分布（边界案例代理） ===')
    for k, v in sorted(st_dist.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v}')
    tree['strategy_distribution'] = st_dist
    with open(os.path.join(DATA, 'fault_tree.json'), 'w', encoding='utf-8') as f:
        json.dump(tree, f, ensure_ascii=False, indent=2)
    conn.close()
    print(f'\n写出 fault_tree.json / fault_cases.csv')


if __name__ == '__main__':
    main()
