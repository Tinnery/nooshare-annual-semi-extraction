"""DEPRECATED: This script has been migrated to the package.
Use: python -m annual_semi_extraction.cli h1-extract
"""
#!/usr/bin/env python3
"""
h1_frozen_judge.py — 冻结组合库判定程序（纯函数，无副作用）

被 h1_extractor.py 加载，对一份报告的标题序列给出判定：
  freeze_hit_exact      精确命中冻结库某条组合的规范化标题序列
  freeze_hit_signature  命中冻结库某条组合的法规十节指纹
  residual              未命中 → 落残差，进入第二轮积累
  known_failure         未命中，但接近冻结库记录的 near-miss 反例（已知失败模式）

设计约束：
  - 只读冻结库，不修改任何输入
  - 判定过程确定性（无随机、无 IO 写、无网络）
  - 冻结库 sha256 强校验，加载即登记版本，保证可复现与可回滚
"""
import re
import difflib
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = BASE / 'data' / 'h1_frozen_combo_library.json'
SHA_FILE = BASE / 'data' / 'h1_frozen_library_sha256.txt'

SEC_NUM_PAT = re.compile(r'^第[一二三四五六七八九十百零〇]+[节章]\s*[:：]?\s*')
DOTS_PAT = re.compile(r'[\.。…·]{2,}.*$')

SECTION_VARIANTS = {
    1: ['重要提示、目录和释义', '释义', '重要提示', '重要提示及目录', '重要提示、目录',
        '备查文件目录', '目录和释义', '重要提示和释义', '目录'],
    2: ['公司简介和主要财务指标', '公司简介', '公司基本情况', '公司概况',
        '会计数据和财务指标摘要', '会计数据和财务指标'],
    3: ['管理层讨论与分析', '经营情况讨论与分析', '董事会报告'],
    4: ['公司治理', '公司治理、环境和社会', '公司治理报告', '企业管治报告'],
    5: ['环境和社会责任', '环境与社会责任', '环境、社会责任和其他公司治理'],
    6: ['重要事项'],
    7: ['股份变动及股东情况', '普通股股份变动及股东情况'],
    8: ['优先股相关情况'],
    9: ['债券相关情况', '公司债券相关情况'],
    10: ['财务报告', '财务会计报告'],
}


def norm(h):
    h = SEC_NUM_PAT.sub('', str(h).strip())
    h = DOTS_PAT.sub('', h)
    h = re.sub(r'\s+', '', h)
    return h


def canon_match(a, b):
    if not a or not b:
        return False
    if a == b or b.startswith(a) or a.startswith(b):
        return True
    if abs(len(a) - len(b)) <= 2:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85
    return False


def fingerprint_key(headings):
    ns = [norm(h) for h in headings if norm(h)]
    secs = [i for i in range(1, 11)
            if any(canon_match(norm(a), p) for a in SECTION_VARIANTS[i] for p in ns)]
    extras = []
    for p in ns:
        if any(canon_match(norm(a), p) for i in range(1, 11) for a in SECTION_VARIANTS[i]):
            continue
        extras.append(p)
    return json.dumps({'sections': secs, 'extras': sorted(set(extras))},
                      ensure_ascii=False, separators=(',', ':'))


def exact_key(headings):
    return '|'.join(norm(h) for h in headings)


class FrozenJudge:
    def __init__(self, library_path=None, verify_sha=True):
        p = Path(library_path) if library_path else DEFAULT_LIBRARY
        if not p.exists():
            raise FileNotFoundError('冻结库不存在: %s' % p)
        raw = p.read_text(encoding='utf-8')
        self.library_sha256 = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        if verify_sha and SHA_FILE.exists():
            registered = SHA_FILE.read_text(encoding='utf-8').split()[1]
            if registered != self.library_sha256:
                raise ValueError('冻结库 sha256 与登记不符: %s vs %s'
                                 % (self.library_sha256[:12], registered[:12]))
        lib = json.loads(raw)
        self.version = lib['metadata']['version']
        self.library_path = str(p)
        self.exact_map = {}
        self.fp_map = {}
        self.combo_by_id = {}
        self.near_miss = []
        for c in lib['combinations']:
            self.exact_map.setdefault(c['exact_key'], []).append(c['combo_id'])
            self.fp_map.setdefault(c['fingerprint_key'], []).append(c['combo_id'])
            self.combo_by_id[c['combo_id']] = c
            for nm in c['near_miss']:
                self.near_miss.append((exact_key(nm['headings']), c['combo_id'], nm['status']))
        self.n_combos = len(lib['combinations'])

    def _resolve_fp(self, fk, headings):
        """签名命中时按确定性规则选唯一代表组合，不罗列全部。

        排序键（全部确定性）：
          1. 与输入标题序列的文本相似度最高（difflib，tie 时由后续键裁决）
          2. 组合 count 最大（边际覆盖优先）
          3. combo_id 字典序最小（最终 tie-break）
        """
        ids = self.fp_map.get(fk, [])
        if not ids:
            return None
        ek = exact_key(headings)
        scored = []
        for cid in ids:
            c = self.combo_by_id[cid]
            ratio = difflib.SequenceMatcher(None, ek, c['exact_key']).ratio()
            scored.append((-round(ratio, 6), -c['count'], cid))
        scored.sort()
        best = scored[0]
        return {'combo_id': best[2], 'similarity': -best[0],
                'candidates_in_signature': len(ids)}

    def judge(self, headings):
        """返回判定 dict；输入为标题字符串列表或 heading dict 列表。"""
        hs = []
        for h in headings or []:
            hs.append(h.get('canonical_name') or h.get('raw_name') if isinstance(h, dict) else str(h))
        hs = [h for h in hs if h]
        ek, fk = exact_key(hs), fingerprint_key(hs)
        base = {
            'library_version': self.version,
            'library_sha256': self.library_sha256,
            'n_headings': len(hs),
            'fingerprint': fk,
        }
        if ek in self.exact_map:
            ids = self.exact_map[ek]
            return {**base, 'verdict': 'freeze_hit_exact',
                    'matched_combo': ids[0], 'all_exact_hits': ids,
                    'match_level': 'exact'}
        if fk in self.fp_map:
            rep = self._resolve_fp(fk, hs)
            return {**base, 'verdict': 'freeze_hit_signature',
                    'matched_combo': rep['combo_id'],
                    'match_similarity': rep['similarity'],
                    'candidates_in_signature': rep['candidates_in_signature'],
                    'match_level': 'signature'}
        # 已知失败模式：与某条 near-miss 反例高度相似
        best, best_id, best_status = 0.0, None, None
        for nm_key, cid, status in self.near_miss:
            r = difflib.SequenceMatcher(None, ek, nm_key).ratio()
            if r > best:
                best, best_id, best_status = r, cid, status
        if best >= 0.90:
            return {**base, 'verdict': 'known_failure',
                    'matched_combos': [], 'match_level': 'none',
                    'near_miss_combo': best_id, 'near_miss_similarity': round(best, 3),
                    'near_miss_status': best_status}
        return {**base, 'verdict': 'residual', 'matched_combos': [],
                'match_level': 'none'}


_SINGLETON = None


def get_judge(library_path=None):
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = FrozenJudge(library_path)
    return _SINGLETON
