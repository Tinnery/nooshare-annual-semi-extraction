#!/usr/bin/env python3
"""
步骤 3 补充：第二轮残差分级（把「可确认候选」与「失败模式」分开）

根因：按频次直接把残差最高频组合入冻结库是错的。
786 份 `sections=[1]` 是单节碎片，属于提取失败，不是合法组合。
本脚本按法规十节对每个残差指纹分级：
  ELIGIBLE   十节 always 齐全、无额外节 → 可作入冻结库候选（须补确认证据）
  VARIANT    十节齐全但有额外节 → 需人工判断额外节是否合法（如监事会报告）
  FAILURE    其余 → 提取失败/缺失，进故障归因，不入冻结库
"""
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))
from h1_frozen_judge import fingerprint_key  # noqa: E402

ALWAYS = {1, 2, 3, 4, 5, 6, 7, 10}
COND = {8, 9}
TEN = ALWAYS | COND


def classify(fp):
    s = set(fp['sections'])
    ex = fp['extras']
    if not s and not ex:
        return 'FAILURE', 'empty_no_headings'
    if len(s) <= 1:
        return 'FAILURE', 'single_section_fragment'
    if ALWAYS <= s and s <= TEN and not ex:
        return 'ELIGIBLE', 'full_always_sections_no_extras'
    if ALWAYS <= s and not ex:
        return 'ELIGIBLE', 'full_always_sections_with_conditional'
    if ALWAYS <= s and ex:
        return 'VARIANT', 'full_always_plus_extra_sections'
    if len(s) >= 6:
        return 'FAILURE', 'near_full_missing_core_sections'
    return 'FAILURE', 'partial_incomplete'


def main():
    src = BASE / 'data' / 'frozen_replay_round1.jsonl'
    by_fp = defaultdict(lambda: {'n': 0, 'slots': [],
                                 'layers': Counter(), 'methods': Counter()})
    with src.open(encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if r['verdict'] in ('freeze_hit_exact', 'freeze_hit_signature'):
                continue
            fp = json.loads(r['fingerprint'])
            key = r['fingerprint']
            d = by_fp[key]
            d['n'] += 1
            if len(d['slots']) < 5:
                d['slots'].append(r['slot_key'])
            d['layers'][(r['report_year'], r['period'])] += 1
            d['methods'][r['extraction_method']] += 1

    classes = Counter()
    reasons = Counter()
    items = []
    for key, d in by_fp.items():
        fp = json.loads(key)
        cls, reason = classify(fp)
        classes[cls] += d['n']
        reasons[reason] += d['n']
        items.append({
            'fingerprint': key,
            'n_reports': d['n'],
            'class': cls,
            'reason': reason,
            'example_slots': d['slots'],
            'layer_distribution': {'%s_p%s' % k: v for k, v in d['layers'].most_common()},
            'method_distribution': dict(d['methods']),
            'action': {
                'ELIGIBLE': '进入第二轮确认队列：补 legal_basis + near_miss + 确认主体后方可入冻结库',
                'VARIANT': '人工判断额外节合法性（如 A+H 的监事会报告 / 致股东的信），确认后入 VARIANT 库',
                'FAILURE': '进故障归因（版式异常/算法边界/MD 残缺），不得入冻结库',
            }[cls],
        })
    items.sort(key=lambda x: -x['n_reports'])

    eligible = [x for x in items if x['class'] == 'ELIGIBLE']
    variant = [x for x in items if x['class'] == 'VARIANT']
    failure = [x for x in items if x['class'] == 'FAILURE']

    out = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'source': 'data/frozen_replay_round1.jsonl (只读)',
            'regulatory_basis': '证监会公告〔2021〕15/16号正文十节；always={1,2,3,4,5,6,7,10}, conditional={8,9}',
            'principle': '频次只作候选排序，不作正确性裁判；碎片/缺失组合不得入冻结库',
        },
        'summary': {
            'n_residual_reports': sum(x['n_reports'] for x in items),
            'n_residual_fingerprints': len(items),
            'class_distribution_reports': dict(classes),
            'reason_distribution_reports': dict(reasons),
            'n_eligible_fingerprints': len(eligible),
            'n_eligible_reports': sum(x['n_reports'] for x in eligible),
            'n_variant_fingerprints': len(variant),
            'n_variant_reports': sum(x['n_reports'] for x in variant),
            'n_failure_fingerprints': len(failure),
            'n_failure_reports': sum(x['n_reports'] for x in failure),
        },
        'eligible_candidates': eligible,
        'variant_candidates': variant,
        'failure_categories': [
            {'reason': r, 'n_reports': n,
             'n_fingerprints': sum(1 for x in failure if x['reason'] == r)}
            for r, n in reasons.most_common() if r in
            {'empty_no_headings', 'single_section_fragment',
             'near_full_missing_core_sections', 'partial_incomplete'}
        ],
        'all_fingerprints': items,
    }
    p = BASE / 'data' / 'frozen_round2_classified.json'
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')

    print('=== 第二轮残差分级 ===')
    print('  残差报告 %d, 唯一指纹 %d'
          % (out['summary']['n_residual_reports'], out['summary']['n_residual_fingerprints']))
    print('  按报告数:', dict(classes))
    print('  ELIGIBLE 指纹 %d (覆盖 %d 份)'
          % (len(eligible), out['summary']['n_eligible_reports']))
    print('  VARIANT  指纹 %d (覆盖 %d 份)'
          % (len(variant), out['summary']['n_variant_reports']))
    print('  FAILURE  指纹 %d (覆盖 %d 份)'
          % (len(failure), out['summary']['n_failure_reports']))
    print('\n=== ELIGIBLE 候选（按覆盖排序）===')
    for x in eligible[:10]:
        print('  %4d 份  %s' % (x['n_reports'], x['fingerprint'][:100]))
    print('\n输出:', p)


if __name__ == '__main__':
    main()
