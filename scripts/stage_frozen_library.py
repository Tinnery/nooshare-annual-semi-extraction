#!/usr/bin/env python3
"""
步骤 1：构建冻结组合库（带确认证据链）

输入：
  data/h1_clean_combo_template.json   27 个 clean 组合
  data/h1_combo_audit.json           Top100 审核清单（near-miss 反例来源）
  annual_semi_extraction/spec/regulatory_versions.json  5 份法规原文 sha256
  annual_semi_extraction/spec/legal_chapters.json      法规十节定义

输出：
  data/h1_frozen_combo_library.json  冻结库（含 confirmed_by / legal_basis / near_miss）
  data/h1_frozen_library_sha256.txt 冻结库 sha256 登记

设计要点：
  - confirmed_by 如实记录来源为规则脚本审核，human_confirmed=false（不伪造人工确认）
  - legal_basis 绑定到法规原文 PDF sha256 + 具体节号
  - near_miss 从审核清单里被拒的组合中取最相似者，附拒绝理由
  - 每条组合带 fingerprint（法规十节签名），供步骤 2 判定使用
  - 组合中残留的粘连噪声如实标 impurities，不假装干净
"""
import json
import re
import difflib
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))
# 指纹/规范化函数与运行时判定程序共用同一实现，杜绝构建期与运行期漂移
from h1_frozen_judge import norm, canon_match, fingerprint_key, exact_key  # noqa: E402

# ---- 法规基准：十节（证监会公告〔2021〕15号 / 16号 正文） ----
LEGAL_10 = [
    '重要提示、目录和释义', '公司简介和主要财务指标', '管理层讨论与分析', '公司治理',
    '环境和社会责任', '重要事项', '股份变动及股东情况', '优先股相关情况',
    '债券相关情况', '财务报告',
]
FIRST_ALIASES = ['重要提示、目录和释义', '释义', '重要提示及目录', '重要提示和释义',
                 '重要提示、目录、释义', '重要提示', '目录', '备查文件目录']
# 第一节变体（组合里出现的合法变体）
SECTION_VARIANTS = {
    1: ['重要提示、目录和释义', '释义', '重要提示', '重要提示及目录', '重要提示、目录',
        '备查文件目录', '目录和释义', '重要提示和释义'],
    2: ['公司简介和主要财务指标', '公司简介', '公司基本情况', '公司概况'],
    3: ['管理层讨论与分析', '经营情况讨论与分析', '董事会报告'],
    4: ['公司治理', '公司治理、环境和社会', '公司治理报告'],
    5: ['环境和社会责任', '环境与社会责任', '环境、社会责任和其他公司治理'],
    6: ['重要事项'],
    7: ['股份变动及股东情况', '普通股股份变动及股东情况'],
    8: ['优先股相关情况'],
    9: ['债券相关情况', '公司债券相关情况'],
    10: ['财务报告', '财务会计报告'],
}

def fingerprint(headings):
    """法规十节签名，复用运行时判定程序的实现"""
    key = fingerprint_key(headings)
    obj = json.loads(key)
    return tuple(obj['sections']), tuple(obj['extras'])


def fp_str(fp):
    return json.dumps({'sections': list(fp[0]), 'extras': list(fp[1])},
                      ensure_ascii=False, separators=(',', ':'))


def detect_impurities(headings):
    """如实标出组合里残留的粘连噪声（不等于判定错误，仅记录）"""
    bad = []
    for i, h in enumerate(headings, 1):
        n = norm(h)
        if len(n) > 20:
            bad.append({'pos': i, 'heading': h, 'reason': '标题过长，疑似正文粘连'})
        elif any(k in n for k in ['本报告书中', '报告期公司不存在', '适用', '审计报告',
                                  '保证', '真实、准确', '董事会']):
            bad.append({'pos': i, 'heading': h, 'reason': '含正文/表单残留文本'})
        elif ' ' in str(h).strip() and re.search(r'\S\s+\S', str(h).strip()):
            bad.append({'pos': i, 'heading': h, 'reason': '标题内部含空格（如「释 义」）'})
    return bad


def build_legal_basis(fp, reg_versions, legal_chapters):
    """为一条组合绑定法规原文 sha + 命中的具体节"""
    key = 'no2_2021_15'  # 年报 2021-2024（27 条 clean 组合的主体适用版本）
    semi = 'no3_2021_16'
    rv = {v['original_file'].split('/')[-1].replace('.pdf', ''): v
          for v in reg_versions['versions']}
    entries = []
    for reg_key, label in [(key, '年报'), (semi, '半年报')]:
        v = rv.get(reg_key)
        if not v:
            continue
        chap = legal_chapters['chapters'][reg_key]
        matched = []
        for sec in chap['sections']:
            m = re.search(r'第([一二三四五六七八九十]+)节', sec['marker'])
            cn = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
                  '七': 7, '八': 8, '九': 9, '十': 10}
            num = cn.get(m.group(1), 0) if m else 0
            if num in fp[0]:
                matched.append({'marker': sec['marker'], 'name': sec['name'],
                                'required': sec['required']})
        entries.append({
            'scope': label,
            'standard': v['standard'],
            'document_no': v['document_no'],
            'effective_from': v['effective_from'],
            'original_file': v['original_file'],
            'original_sha256': v['original_sha256'],
            'matched_sections': matched,
        })
    return {
        'authority': '证监会公告〔2021〕15号（年报第2号）/〔2021〕16号（半年报第3号）正文十节',
        'registry_source': 'annual_semi_extraction/spec/regulatory_versions.json',
        'chapters_source': 'annual_semi_extraction/spec/legal_chapters.json',
        'note': '第一节允许别名；第8/9节为 conditional（发行优先股/债券才须披露）；'
                '「备查文件目录」不属法定正文十节，仅作前后置节',
        'versions': entries,
    }


def find_near_miss(headings, audit_results, topn=2):
    """从被拒组合里找最相似的反例，附拒绝理由"""
    target = [norm(h) for h in headings]
    target_joined = '|'.join(target)
    scored = []
    for r in audit_results:
        if r['status'] == 'valid':
            continue
        cand = [norm(h) for h in r['headings']]
        ratio = difflib.SequenceMatcher(None, target_joined, '|'.join(cand)).ratio()
        scored.append((ratio, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for ratio, r in scored[:topn]:
        if ratio < 0.55:
            continue
        out.append({
            'similarity': round(ratio, 3),
            'status': r['status'],
            'count': r['count'],
            'n_headings': r['n_headings'],
            'headings': r['headings'],
            'rejection_reasons': r.get('issues', []),
            'why_it_is_a_near_miss': '结构与本组合高度相似，但被审核判为 %s，'
                                     '说明仅凭文本相似度不能作为正确性裁判' % r['status'],
        })
    return out


def main():
    clean = json.loads((BASE / 'data/h1_clean_combo_template.json').read_text(encoding='utf-8'))
    audit = json.loads((BASE / 'data/h1_combo_audit.json').read_text(encoding='utf-8'))
    reg = json.loads((BASE / 'annual_semi_extraction/spec/regulatory_versions.json').read_text(encoding='utf-8'))
    chap = json.loads((BASE / 'annual_semi_extraction/spec/legal_chapters.json').read_text(encoding='utf-8'))

    source_sha = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [BASE / 'data/h1_clean_combo_template.json',
                  BASE / 'data/h1_combo_audit.json',
                  BASE / 'annual_semi_extraction/spec/regulatory_versions.json',
                  BASE / 'annual_semi_extraction/spec/legal_chapters.json']
    }

    combos = []
    for i, x in enumerate(clean['clean_combinations'], 1):
        hs = x['headings']
        fp = fingerprint(hs)
        combo_id = 'FC%02d' % i
        entry = {
            'combo_id': combo_id,
            'headings': hs,
            'canonical_cats': x.get('canonical_cats'),
            'n_headings': x['n_headings'],
            'count': x['count'],
            'n_issuers': x.get('n_issuers'),
            'year_range': x.get('year_range'),
            'periods': x.get('periods'),
            'complete_rate': x.get('complete_rate'),
            'source_status': x.get('status'),
            'fingerprint': {'sections': list(fp[0]), 'extras': list(fp[1])},
            'fingerprint_key': fp_str(fp),
            'exact_key': exact_key(hs),
            'confirmed_by': {
                'method': 'rule_based_audit',
                'source_artifact': 'data/h1_combo_audit.json (Top100 审核清单)',
                'source_status': 'valid',
                'confirmed_at': '2026-03-13',
                'confirmed_by': 'agent:automated-combo-audit-v1.0',
                'human_confirmed': False,
                'human_review_required': True,
                'note': '确认主体是规则脚本审核，不是人类逐条标注；'
                        '按 M1/M2 要求，人工确认闭环前不得声称「已确认」。',
            },
            'legal_basis': build_legal_basis(fp, reg, chap),
            'near_miss': find_near_miss(hs, audit['audit_results']),
            'impurities': detect_impurities(hs),
        }
        combos.append(entry)

    fps = {}
    for c in combos:
        fps.setdefault(c['fingerprint_key'], []).append(c['combo_id'])

    lib = {
        'metadata': {
            'name': 'h1_frozen_combo_library',
            'version': '1.0.0',
            'frozen_at': datetime.now(timezone.utc).isoformat(),
            'authority': 'deliverables/01-requirement.md (v2) E1; 本库为判定程序，变更须走 MINOR/MAJOR',
            'description': '经规则审核确认的一级标题组合冻结库，供 h1_extractor 加载作为判定依据',
            'n_combos': len(combos),
            'n_unique_fingerprints': len(fps),
            'decision_rule': 'exact_key 精确命中 → freeze_hit_exact; '
                             '否则 fingerprint_key 命中 → freeze_hit_signature; '
                             '否则 → residual（落残差，进入第二轮积累）',
            'important_caveats': [
                'confirmed_by.human_confirmed = false：27 条均为规则脚本审核，无人类逐条确认记录',
                '冻结库 27 条来自旧版提取器，canonical_cats 与当前 v2_reg_anchored 不兼容；'
                '判定改用法规十节指纹，可跨版本对齐',
                '部分组合仍含粘连噪声，已逐条记入 impurities，未假装干净',
                '「备查文件目录」不是法定正文十节，仅作前后置节处理',
            ],
            'source_sha256': source_sha,
        },
        'fingerprint_index': fps,
        'combinations': combos,
    }

    out = BASE / 'data/h1_frozen_combo_library.json'
    payload = json.dumps(lib, ensure_ascii=False, indent=2, sort_keys=True)
    out.write_text(payload, encoding='utf-8')
    sha = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    (BASE / 'data/h1_frozen_library_sha256.txt').write_text(
        'h1_frozen_combo_library.json  %s  version=1.0.0  frozen_at=%s\n'
        % (sha, lib['metadata']['frozen_at']), encoding='utf-8')

    print('冻结库已生成:', out)
    print('  组合数:', len(combos))
    print('  唯一指纹:', len(fps))
    print('  带 near_miss 的组合:', sum(1 for c in combos if c['near_miss']))
    print('  带 legal_basis 的组合:', sum(1 for c in combos if c['legal_basis']['versions']))
    print('  human_confirmed=true 的组合:', sum(1 for c in combos if c['confirmed_by']['human_confirmed']))
    print('  含 impurities 的组合:', sum(1 for c in combos if c['impurities']))
    print('  sha256:', sha)


if __name__ == '__main__':
    main()
