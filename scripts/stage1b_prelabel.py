#!/usr/bin/env python3
"""
阶段1b 预标注：用法规基准对 301 份金标准样本自动标注。

输出：data/stage1b_worksheet_prelabel.csv
- 新增列：pre_correct, pre_wrong, pre_missed, pre_legal_rate, pre_notes
- 人工只需审核修正 pre_* 列，填入 label_* 列

法规基准：证监会公告〔2021〕15号/16号，正文十节
"""
import csv
import re
import json
from pathlib import Path

# ── 法规十节 ──
LEGAL_10 = [
    '重要提示、目录和释义',
    '公司简介和主要财务指标',
    '管理层讨论与分析',
    '公司治理',
    '环境和社会责任',
    '重要事项',
    '股份变动及股东情况',
    '优先股相关情况',
    '债券相关情况',
    '财务报告',
]

# ── 别名映射（规范化后 → 法规节号 1-10） ──
ALIAS_MAP = {
    # 第一节：释义 / 重要提示
    '释义': 1,
    '重要提示': 1,
    '重要提示、目录和释义': 1,
    '目录和释义': 1,
    '重要提示、目录': 1,
    '目录': 1,
    # 第二节
    '公司简介和主要财务指标': 2,
    '公司简介': 2,
    '公司简介及主要财务指标': 2,
    '公司基本情况': 2,
    '公司概况': 2,
    # 第三节
    '管理层讨论与分析': 3,
    '经营情况讨论与分析': 3,
    '董事会报告': 3,
    '经营情况回顾及展望': 3,
    '经营业绩回顾及展望': 3,
    # 第四节
    '公司治理': 4,
    '公司治理、环境和社会': 4,
    # 第五节
    '环境和社会责任': 5,
    '环境与社会责任': 5,
    '环境保护与可持续发展': 5,
    '社会责任': 5,
    # 第六节
    '重要事项': 6,
    # 第七节
    '股份变动及股东情况': 7,
    '股份变动及主要股东持股情况': 7,
    '股本变动及股东情况': 7,
    '股份变动': 7,
    # 第八节
    '优先股相关情况': 8,
    # 第九节
    '债券相关情况': 9,
    '公司债券相关情况': 9,
    # 第十节
    '财务报告': 10,
    '财务会计报告': 10,
    '财务报表': 10,
    '审计意见及财务报表': 10,
}

# 法规节号 → 标准名
SEC_NUM_TO_NAME = {i+1: name for i, name in enumerate(LEGAL_10)}

# ── 规范化函数 ──
def norm_heading(h: str) -> str:
    """去除编号前缀、空白、标点，得到纯章节名"""
    h = h.strip()
    # 去 "第X节" 前缀
    h = re.sub(r'^第[一二三四五六七八九十百零\d]+节\s*', '', h)
    # 去数字编号 "1 " "1. " "1、"
    h = re.sub(r'^\d+[\s.、．.]+\s*', '', h)
    # 去多余空白
    h = re.sub(r'\s+', '', h)
    # 去尾部标点
    h = h.rstrip('，。、,.')
    return h


def match_legal(h: str) -> int | None:
    """返回匹配的法规节号 (1-10)，None 表示不匹配"""
    n = norm_heading(h)
    if n in ALIAS_MAP:
        return ALIAS_MAP[n]
    # 模糊匹配：包含关系
    for alias, sec in ALIAS_MAP.items():
        if alias in n or n in alias:
            return sec
    return None


def parse_headings(raw: str) -> list[str]:
    """解析 pipe-separated headings"""
    if not raw or not raw.strip():
        return []
    return [h.strip() for h in raw.split('|') if h.strip()]


def prelabel_row(row: dict) -> dict:
    """对单行做预标注"""
    pdf_hs = parse_headings(row.get('pdf_headings', ''))
    toc_hs = parse_headings(row.get('toc_headings', ''))
    md_hs = parse_headings(row.get('md_headings', ''))

    # 1. 逐条判定 PDF headings
    correct_nums = []
    wrong_items = []
    matched_secs = set()

    for i, h in enumerate(pdf_hs, 1):
        sec = match_legal(h)
        if sec is not None:
            correct_nums.append(i)
            matched_secs.add(sec)
        else:
            # 分类错误类型
            n = norm_heading(h)
            if len(n) <= 4:
                reason = 'junk'  # 太短，可能是封面/页眉
            elif any(kw in n for kw in ['备查文件', '信息披露', '索引']):
                reason = 'junk'  # 非法定章节
            elif any(kw in n for kw in ['致辞', '董事长', '总裁']):
                reason = 'junk'  # 非一级标题
            else:
                reason = 'wrong'  # 可能是子章节误报
            wrong_items.append(f'{i}:{n[:12]}={reason}')

    # 2. 检查漏报
    # 用 toc_headings 作为参考（注意：toc 也可能不完整，但作为辅助参考）
    ref_hs = toc_hs if toc_hs else md_hs
    missed = []
    for h in ref_hs:
        sec = match_legal(h)
        if sec is not None and sec not in matched_secs:
            missed.append(f's{sec}:{norm_heading(h)[:12]}')

    # 3. 格式化输出
    if len(correct_nums) == len(pdf_hs) and not wrong_items:
        correct_str = 'ALL'
    elif correct_nums:
        # 压缩连续编号
        correct_str = compress_nums(correct_nums)
    else:
        correct_str = ''

    wrong_str = ' | '.join(wrong_items) if wrong_items else ''
    missed_str = ' | '.join(missed) if missed else ''

    # 4. 法规符合率
    legal_rate = len(matched_secs) / 10.0

    # 5. 预标注备注
    notes = []
    if not pdf_hs:
        notes.append('NO_PDF_HEADINGS')
    if legal_rate < 0.6:
        notes.append(f'LOW_LEGAL={legal_rate:.1f}')
    if len(pdf_hs) > 15:
        notes.append(f'OVER_SEGMENTED({len(pdf_hs)})')
    if len(pdf_hs) < 5 and legal_rate < 1.0:
        notes.append(f'UNDER_SEGMENTED({len(pdf_hs)})')

    return {
        'pre_correct': correct_str,
        'pre_wrong': wrong_str,
        'pre_missed': missed_str,
        'pre_legal_rate': f'{legal_rate:.2f}',
        'pre_n_pdf': len(pdf_hs),
        'pre_n_matched': len(matched_secs),
        'pre_notes': '; '.join(notes),
    }


def compress_nums(nums: list[int]) -> str:
    """压缩连续编号：[1,2,3,5,7,8,9] -> '1-3,5,7-9'"""
    if not nums:
        return ''
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f'{start}-{prev}' if start != prev else str(start))
            start = prev = n
    ranges.append(f'{start}-{prev}' if start != prev else str(start))
    return ','.join(ranges)


def main():
    base = Path(__file__).resolve().parent.parent
    infile = base / 'data' / 'stage1b_worksheet.csv'
    outfile = base / 'data' / 'stage1b_worksheet_prelabel.csv'

    with open(infile, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    # 新增列
    new_cols = list(rows[0].keys()) + [
        'pre_correct', 'pre_wrong', 'pre_missed',
        'pre_legal_rate', 'pre_n_pdf', 'pre_n_matched', 'pre_notes'
    ]

    results = []
    stats = {'all_correct': 0, 'partial': 0, 'no_pdf': 0, 'low_legal': 0, 'total': 0}

    for row in rows:
        pre = prelabel_row(row)
        merged = {**row, **pre}
        results.append(merged)
        stats['total'] += 1

        lr = float(pre['pre_legal_rate'])
        if pre['pre_n_pdf'] == 0:
            stats['no_pdf'] += 1
        elif pre['pre_wrong'] == '' and pre['pre_missed'] == '':
            stats['all_correct'] += 1
        elif lr < 0.6:
            stats['low_legal'] += 1
        else:
            stats['partial'] += 1

    with open(outfile, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_cols)
        writer.writeheader()
        writer.writerows(results)

    print(f'预标注完成: {outfile}')
    print(f'总样本: {stats["total"]}')
    print(f'  全匹配 (ALL, 无漏报): {stats["all_correct"]}')
    print(f'  部分匹配: {stats["partial"]}')
    print(f'  无 PDF 标题: {stats["no_pdf"]}')
    print(f'  低法规符合率 (<0.6): {stats["low_legal"]}')

    # 输出需要人工重点审核的样本
    review = [r for r in results if r['pre_wrong'] or r['pre_missed'] or float(r['pre_legal_rate']) < 0.8]
    print(f'\n需人工审核: {len(review)} 份')
    for r in review[:10]:
        print(f'  {r["sample_id"]} [{r["layer"]}] lr={r["pre_legal_rate"]} '
              f'wrong=[{r["pre_wrong"][:60]}] missed=[{r["pre_missed"][:60]}]')


if __name__ == '__main__':
    main()
