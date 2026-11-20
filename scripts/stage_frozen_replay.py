#!/usr/bin/env python3
"""
步骤 3：全量只读回放 + 第二轮积累（残差驱动）

输入（只读，永不修改）：
  data/h1_full.jsonl            第一轮全量提取结果（replay set，38,350 份）

输出：
  data/frozen_replay_round1.jsonl    每份报告的判定结果（新增，不改原文件）
  data/frozen_hit_set_sha256.txt     第一轮命中集合 sha256
  data/frozen_residual_sha256.txt    第一轮残差集合 sha256
  data/frozen_round2_candidates.json 第二轮高频候选 + 边际新增覆盖
  data/frozen_round1_report.json     分层统计与证据链

方法：
  - 命中：frozen_verdict ∈ {freeze_hit_exact, freeze_hit_signature}
  - 残差：residual / known_failure（落第二轮候选池）
  - 命中集合 sha256 = 排序后的 slot_key 列表的 sha（确定性、可复现）
  - 边际新增覆盖：把每个候选组合的指纹加入冻结库后能新增命中多少份
  - 分层：year × period × extraction_method（对齐 01 §五.2 / U-H1.3）
"""
import json
import sys
import hashlib
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))
from h1_frozen_judge import FrozenJudge, fingerprint_key, exact_key  # noqa: E402

HIT_VERDICTS = {'freeze_hit_exact', 'freeze_hit_signature'}


def sha_of_list(items):
    h = hashlib.sha256()
    for x in sorted(items):
        h.update(x.encode('utf-8'))
        h.update(b'\n')
    return h.hexdigest()


def main():
    src = BASE / 'data' / 'h1_full.jsonl'
    if not src.exists():
        raise SystemExit('缺少 replay set: %s' % src)
    src_sha = hashlib.sha256(src.read_bytes()).hexdigest()

    judge = FrozenJudge()
    out_path = BASE / 'data' / 'frozen_replay_round1.jsonl'

    hits, residuals = [], []
    verdict_counter = Counter()
    layer_stats = defaultdict(lambda: Counter())
    residual_fp = Counter()
    residual_exact = Counter()
    matched_combo = Counter()
    n = 0

    with src.open(encoding='utf-8') as fin, out_path.open('w', encoding='utf-8') as fout:
        for line in fin:
            rec = json.loads(line)
            hs = [h.get('canonical_name') or h.get('raw_name')
                  for h in (rec.get('headings') or [])]
            v = judge.judge(hs)
            verdict_counter[v['verdict']] += 1
            n += 1

            slot = rec['slot_key']
            layer = (rec['report_year'], rec['period'], rec['extraction_method'])
            layer_stats[layer][v['verdict']] += 1

            out = {
                'slot_key': slot,
                'report_year': rec['report_year'],
                'period': rec['period'],
                'extraction_method': rec['extraction_method'],
                'is_complete_l1': rec['is_complete_l1'],
                'verdict': v['verdict'],
                'matched_combo': v.get('matched_combo'),
                'match_level': v.get('match_level'),
                'fingerprint': v['fingerprint'],
                'n_headings': v['n_headings'],
            }
            fout.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + '\n')

            if v['verdict'] in HIT_VERDICTS:
                hits.append(slot)
                if v.get('matched_combo'):
                    matched_combo[v['matched_combo']] += 1
            else:
                residuals.append(slot)
                residual_fp[v['fingerprint']] += 1
                residual_exact[exact_key(hs)] += 1

            if n % 10000 == 0:
                print('  进度 %d, 命中 %d, 残差 %d' % (n, len(hits), len(residuals)), flush=True)

    hit_sha = sha_of_list(hits)
    residual_sha = sha_of_list(residuals)
    (BASE / 'data' / 'frozen_hit_set_sha256.txt').write_text(
        'round1_hit_set n=%d sha256=%s\n' % (len(hits), hit_sha), encoding='utf-8')
    (BASE / 'data' / 'frozen_residual_sha256.txt').write_text(
        'round1_residual_set n=%d sha256=%s\n' % (len(residuals), residual_sha), encoding='utf-8')

    # ---- 第二轮候选：残差按指纹聚合，计算边际新增覆盖 ----
    base_fp = set(judge.fp_map.keys())
    candidates = []
    for fp, cnt in residual_fp.most_common():
        # 边际新增覆盖 = 该指纹若入冻结库可新增命中的份数
        candidates.append({
            'fingerprint': fp,
            'n_residual_reports': cnt,
            'marginal_new_coverage': cnt,
            'marginal_coverage_pct': round(cnt / max(n, 1) * 100, 4),
            'cumulative_coverage_pct': 0.0,
            'status': 'candidate_pending_confirmation',
            'legal_basis_required': True,
            'confirmed_by': None,
            'note': '候选仅由残差频次排序，频次不作正确性裁判（U-H1.3）；'
                    '入冻结库前须补 legal_basis + near_miss + 确认主体',
        })
    cum = len(hits)
    for c in candidates:
        cum += c['marginal_new_coverage']
        c['cumulative_coverage_pct'] = round(cum / max(n, 1) * 100, 4)

    # 分层统计
    layers = []
    for (y, p, m), cnt in sorted(layer_stats.items()):
        total = sum(cnt.values())
        h = sum(cnt[v] for v in HIT_VERDICTS)
        layers.append({'year': y, 'period': p, 'method': m,
                       'total': total, 'hits': h,
                       'residual': total - h,
                       'hit_rate': round(h / total, 4) if total else 0.0,
                       'verdicts': dict(cnt)})

    report = {
        'metadata': {
            'round': 1,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'replay_set': 'data/h1_full.jsonl',
            'replay_set_sha256': src_sha,
            'library_version': judge.version,
            'library_sha256': judge.library_sha256,
            'decision_rule': 'exact/signature 命中即通过；residual/known_failure 落残差',
            'note': 'replay set 只读，本步骤不修改任何既有记录',
        },
        'totals': {
            'n_reports': n,
            'hits': len(hits),
            'residuals': len(residuals),
            'hit_rate': round(len(hits) / n, 4),
            'residual_rate': round(len(residuals) / n, 4),
        },
        'hit_set_sha256': hit_sha,
        'residual_set_sha256': residual_sha,
        'verdict_distribution': dict(verdict_counter),
        'matched_combo_distribution': matched_combo.most_common(),
        'n_unique_residual_fingerprints': len(residual_fp),
        'n_unique_residual_exact_combos': len(residual_exact),
        'baseline_frozen_fingerprints': sorted(base_fp),
        'layers': layers,
        'round2_candidates_top20': candidates[:20],
        'round2_total_candidates': len(candidates),
        'round2_cumulative_at': {
            f'top{k}': round((len(hits) + sum(c['marginal_new_coverage']
                                              for c in candidates[:k])) / n * 100, 2)
            for k in [1, 3, 5, 10, 20, 50]
        },
    }
    (BASE / 'data' / 'frozen_round1_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    (BASE / 'data' / 'frozen_round2_candidates.json').write_text(
        json.dumps({'metadata': report['metadata'],
                    'n_candidates': len(candidates),
                    'candidates': candidates},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')

    print('\n=== 第一轮全量回放 ===')
    print('  总数 %d, 命中 %d (%.2f%%), 残差 %d (%.2f%%)'
          % (n, len(hits), len(hits) / n * 100, len(residuals), len(residuals) / n * 100))
    print('  判定分布:', dict(verdict_counter))
    print('  命中集 sha256:', hit_sha)
    print('  残差集 sha256:', residual_sha)
    print('  残差唯一指纹:', len(residual_fp))
    print('  第二轮候选数:', len(candidates))
    print('  累计覆盖:', report['round2_cumulative_at'])


if __name__ == '__main__':
    main()
