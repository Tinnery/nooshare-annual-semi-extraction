"""阶段1b: 金标准标注底稿生成 + 目录页对齐率(自动外部锚点)

从阶段1a结果分层抽300份, 生成三源并排标注底稿CSV (PDF提取/MD通道/目录页),
并自动计算目录页对齐率 —— 不依赖人工的外部客观指标。
输出: data/stage1b_worksheet.csv, data/stage1b_label_guide.md, data/stage1b_auto_metrics.json
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h1_pdf_core import match_score, norm_heading  # noqa: E402

N_TARGET = 300


def stratified_300(samples):
    by_layer = {}
    for s in samples:
        if s.get('status') != 'ok':
            continue
        by_layer.setdefault(s['layer'], []).append(s)
    total_ok = sum(len(v) for v in by_layer.values())
    quotas = {}
    allocated = 0
    for name, items in sorted(by_layer.items(), key=lambda x: -len(x[1])):
        q = max(2, round(len(items) * N_TARGET / total_ok))
        q = min(q, len(items))
        quotas[name] = q
        allocated += q
    picked = []
    for name, q in quotas.items():
        picked.extend(by_layer[name][:q])
    return picked, quotas


def toc_alignment(sample):
    """目录页条目与PDF提取标题的对齐率(双向 match_score)"""
    toc = sample.get('pdf_meta', {}).get('toc_headings') or []
    if len(toc) < 3:
        return None
    pdf_norms = [norm_heading(h) for h in sample['pdf_headings']]
    hit = 0
    for t in toc:
        tn = norm_heading(t)
        if tn and any(match_score(t, pn) or match_score(pn, tn) for pn in pdf_norms if pn):
            hit += 1
    return hit / len(toc), len(toc), hit


def main():
    with open('data/stage1a_samples.json', 'r', encoding='utf-8') as f:
        samples = json.load(f)

    ws, quotas = stratified_300(samples)
    print(f'抽取 {len(ws)} 份: {quotas}')

    # --- 标注底稿 CSV (utf-8-sig 保证 Excel 打开不乱码) ---
    with open('data/stage1b_worksheet.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['sample_id', 'layer', 'stock_code', 'year', 'period',
                    'md_method', 'md_complete',
                    'pdf_headings', 'md_headings', 'toc_headings',
                    'label_pdf_correct', 'label_pdf_wrong', 'label_missed_h1', 'notes'])
        for i, s in enumerate(ws, 1):
            w.writerow([
                f'S{i:03d}', s['layer'], s['stock_code'], s['report_year'], s['period'],
                s['extraction_method'], s['is_complete_l1'],
                ' | '.join(s['pdf_headings']),
                ' | '.join(s['md_headings']),
                ' | '.join(s.get('pdf_meta', {}).get('toc_headings') or []),
                '', '', '', '',
            ])

    # --- 标注指南 ---
    guide = """# 阶段1b 金标准标注指南

## 任务
对每份样本, 判断 PDF 提取的一级标题是否正确。三列标注:
- `label_pdf_correct`: PDF提取标题中判定正确的编号 (如 "1,2,4-10", 全对填 ALL)
- `label_pdf_wrong`: 判定错误的编号及原因简写 (误报=junk / 归错节=wrong / 漏拼=split)
- `label_missed_h1`: PDF漏掉但该报告实际存在的一级标题 (从目录页/正文中人工确认)

## 判定标准
1. **正确**: 该行确实是该报告的一个一级标题, 且章节名与报告实际章节一致
2. **误报**: 不是一级标题 (正文行/页眉/封面元素被误抓)
3. **漏报**: 对照目录页 (toc_headings 列) 与正文, PDF 提取漏掉的一级标题
4. 半年报 vs 年报章节集不同; 2021年存在新旧两版准则, 以报告自身目录页为准

## 一致性要求
双人独立标注, Cohen's Kappa >= 0.8 方可采信; 分歧样本第三人仲裁。

## 验收
P >= 95% 且 R >= 95% (以标注金标准为唯一权威), 通过后 PDF 通道才有接管资格。
"""
    with open('data/stage1b_label_guide.md', 'w', encoding='utf-8') as f:
        f.write(guide)

    # --- 自动外部锚点: 目录页对齐率 (全量 stage1a 提取成功样本) ---
    ex = [s for s in samples if s.get('status') == 'ok']
    rates, no_toc = [], 0
    for s in ex:
        r = toc_alignment(s)
        if r is None:
            no_toc += 1
            continue
        rates.append(r)
    n_with_toc = len(rates)
    mean_align = sum(r[0] for r in rates) / max(n_with_toc, 1)
    high = sum(1 for r in rates if r[0] >= 0.97)
    perfect = sum(1 for r in rates if r[0] == 1.0)

    # 三源一致性预览: PDF vs TOC vs MD 全对齐样本占比
    triple = 0
    for s in ex:
        r = toc_alignment(s)
        if r is None or not s['md_headings']:
            continue
        if r[0] < 0.95:
            continue
        pdf_norms = [norm_heading(h) for h in s['pdf_headings']]
        md_hit = sum(1 for raw in s['md_headings']
                     if any(match_score(raw, pn) for pn in pdf_norms))
        if md_hit / len(s['md_headings']) >= 0.9:
            triple += 1

    metrics = {
        'n_extracted': len(ex),
        'toc_alignment': {
            'n_with_toc': n_with_toc,
            'n_no_toc': no_toc,
            'mean_align_rate': round(mean_align, 3),
            'align_ge_97pct': high,
            'align_100pct': perfect,
        },
        'triple_source_agree': {'count': triple, 'rate': round(triple / max(len(ex), 1), 3)},
        'worksheet': {'n': len(ws), 'quotas': quotas},
    }
    with open('data/stage1b_auto_metrics.json', 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(json.dumps(metrics['toc_alignment'], ensure_ascii=False))
    print(f"三源一致: {triple}/{len(ex)} = {metrics['triple_source_agree']['rate']:.1%}")
    print('产出: stage1b_worksheet.csv / stage1b_label_guide.md / stage1b_auto_metrics.json')


if __name__ == '__main__':
    main()
