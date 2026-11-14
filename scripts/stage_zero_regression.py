#!/usr/bin/env python3
"""
步骤 4：只读回放零回归验证

验证目标：加载冻结组合库后，h1_extractor 对旧命中集合的既有字段
逐字节不变（diff=0），且判定结果可复现。

方法：
  1. 分层抽样 replay set（year × period × method，每层最多 N 份），
     覆盖第一轮命中集合与残差集合。
  2. 对每份 MD 分别以 H1_FROZEN_EMIT=1 / =0 运行 extract()：
     - 去掉 frozen_verdict 后与 baseline(=0) 逐字节比较
     - 任何差异即判 FAIL（本轮作废）
  3. 对命中集合 sha 重算，验证与步骤 3 登记一致（可复现）。
  4. 输出证据链 JSON。

注意：replay set 只读，本脚本不写任何 MD、不改任何既有结果文件。
"""
import os
import sys
import json
import hashlib
import random
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))

import h1_extractor as E  # noqa: E402
from h1_frozen_judge import FrozenJudge  # noqa: E402

SAMPLE_PER_LAYER = 12


def canonical(rec):
    """既有字段的确定性字节表示（排除新增的 frozen_verdict）"""
    r = {k: v for k, v in rec.items() if k != 'frozen_verdict'}
    return json.dumps(r, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def sha256_of(bytes_list):
    h = hashlib.sha256()
    for b in bytes_list:
        h.update(hashlib.sha256(b).digest())
    return h.hexdigest()


def main():
    judge = FrozenJudge()
    replay = BASE / 'data' / 'frozen_replay_round1.jsonl'
    rounds = {}
    with replay.open(encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            rounds[r['slot_key']] = r

    # 分层抽样：year × period × method × verdict
    buckets = defaultdict(list)
    for slot, r in rounds.items():
        buckets[(r['report_year'], r['period'], r['extraction_method'],
                 r['verdict'])].append(slot)
    rng = random.Random(20261114)  # 固定种子，抽样可复现
    chosen = []
    for k, slots in sorted(buckets.items(), key=lambda x: str(x[0])):
        rng.shuffle(slots)
        chosen.extend(slots[:SAMPLE_PER_LAYER])
    chosen.sort()

    md_root = BASE / 'data' / 'md_cache' / 'published'
    md_files = {E.slot_key_from_path(p): p
                for p in md_root.rglob('*.md')
                if E.slot_key_from_path(p)}

    base_sha_parts, new_sha_parts = [], []
    diffs, verdict_check = [], []
    tested = missing = 0

    for slot in chosen:
        p = md_files.get(slot)
        if p is None:
            missing += 1
            continue
        # baseline: 关闭冻结判定
        os.environ['H1_FROZEN_EMIT'] = '0'
        rec0 = E.extract(p)
        # new: 开启冻结判定
        os.environ['H1_FROZEN_EMIT'] = '1'
        rec1 = E.extract(p)
        if rec0 is None or rec1 is None:
            continue
        tested += 1
        b0, b1 = canonical(rec0), canonical(rec1)
        base_sha_parts.append(b0)
        new_sha_parts.append(b1)
        if b0 != b1:
            diffs.append({'slot_key': slot,
                          'len_base': len(b0), 'len_new': len(b1)})
        v = rec1.get('frozen_verdict', {})
        verdict_check.append({
            'slot_key': slot,
            'expected_verdict': rounds[slot]['verdict'],
            'actual_verdict': v.get('verdict'),
            'library_sha256': v.get('library_sha256'),
        })

    os.environ['H1_FROZEN_EMIT'] = '1'  # 恢复默认

    verdict_mismatch = [x for x in verdict_check
                        if x['expected_verdict'] != x['actual_verdict']]
    lib_shas = {x['library_sha256'] for x in verdict_check if x['library_sha256']}

    # 命中集合 sha 可复现性：严格按步骤3 的原始 jsonl 逐行重算
    # （不可用 dict 去重——38,350 行中有 1,451 个重复 slot，唯一 slot = 36,899，
    #  与 PG 表口径一致；步骤3 登记的是「行级命中集合」sha）
    hit_slots = []
    with replay.open(encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if r['verdict'] in ('freeze_hit_exact', 'freeze_hit_signature'):
                hit_slots.append(r['slot_key'])
    h = hashlib.sha256()
    for s in sorted(hit_slots):
        h.update(s.encode('utf-8'))
        h.update(b'\n')
    recomputed_hit_sha = h.hexdigest()
    registered = (BASE / 'data' / 'frozen_hit_set_sha256.txt').read_text(encoding='utf-8').strip()

    result = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'purpose': 'M3/E4 零回归：加载冻结库后旧命中结论逐字节不变',
            'replay_set': 'data/h1_full.jsonl / data/frozen_replay_round1.jsonl (只读)',
            'md_root': str(md_root),
            'sample_per_layer': SAMPLE_PER_LAYER,
            'random_seed': 20261114,
            'library_version': judge.version,
            'library_sha256': judge.library_sha256,
        },
        'sampling': {
            'n_buckets': len(buckets),
            'n_chosen': len(chosen),
            'n_tested': tested,
            'n_missing_md': missing,
            'verdict_distribution_in_sample': dict(Counter(
                rounds[s]['verdict'] for s in chosen if s in rounds)),
        },
        'zero_regression': {
            'baseline_sha256': sha256_of(base_sha_parts),
            'with_frozen_library_sha256': sha256_of(new_sha_parts),
            'diff_count': len(diffs),
            'diffs': diffs[:20],
            'passed': len(diffs) == 0 and sha256_of(base_sha_parts) == sha256_of(new_sha_parts),
        },
        'verdict_reproducibility': {
            'n_checked': len(verdict_check),
            'n_mismatch': len(verdict_mismatch),
            'mismatches': verdict_mismatch[:20],
            'distinct_library_sha': sorted(lib_shas),
            'passed': len(verdict_mismatch) == 0 and len(lib_shas) == 1,
        },
        'hit_set_reproducibility': {
            'recomputed_sha256': recomputed_hit_sha,
            'registered_line': registered,
            'n_hit_rows': len(hit_slots),
            'n_unique_hit_slots': len(set(hit_slots)),
            'n_duplicate_slots_in_replay': len(hit_slots) - len(set(hit_slots)),
            'basis': '行级命中集合，与步骤3 sha_of_list 一致；重复 slot 不去重',
            'passed': recomputed_hit_sha in registered,
        },
    }
    result['overall_passed'] = all([
        result['zero_regression']['passed'],
        result['verdict_reproducibility']['passed'],
        result['hit_set_reproducibility']['passed'],
    ])
    out = BASE / 'data' / 'frozen_zero_regression.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding='utf-8')

    z = result['zero_regression']
    v = result['verdict_reproducibility']
    print('=== 步骤4 零回归回放 ===')
    print('  抽样桶 %d, 抽中 %d, 本地有 MD 并实测 %d, 缺失 %d'
          % (len(buckets), len(chosen), tested, missing))
    print('  baseline sha :', z['baseline_sha256'])
    print('  frozen   sha :', z['with_frozen_library_sha256'])
    print('  逐字节 diff  :', z['diff_count'], '→', 'PASS' if z['passed'] else 'FAIL')
    print('  判定可复现   : %d 检查, %d 不符 → %s'
          % (v['n_checked'], v['n_mismatch'], 'PASS' if v['passed'] else 'FAIL'))
    print('  命中集 sha   :', 'PASS' if result['hit_set_reproducibility']['passed'] else 'FAIL')
    print('  总判定       :', 'PASS' if result['overall_passed'] else 'FAIL')
    print('  输出:', out)
    return 0 if result['overall_passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
