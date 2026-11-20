#!/usr/bin/env python3
"""
用修复后的 h1_pdf_core.py 重新抽取 301 份金标准样本的 PDF 标题。

读取 stage1b_worksheet.csv，找到每份样本的 slot_key，
从 rustfs 下载 PDF，用修复后的 extract_pdf() 重新抽取，
更新 pdf_headings / pdf_n_headings / pdf_strategy / pdf_purity 列。

输出：data/stage1b_worksheet.csv（原地更新）
"""
import csv
import sys
import os
import urllib3
urllib3.disable_warnings()

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import boto3
from h1_pdf_core import extract_pdf

# rustfs 配置
S3_ENDPOINT = 'https://s3.rustfs.pro.neuralj.com'
S3_KEY = 'charlie'
S3_SECRET = 'sheeta-rustfs'
S3_BUCKET = 'annual-semi'

# PG 配置
PG_HOST = 'pg.pro.neuralj.com'
PG_DB = 'nooshare_dev'
PG_USER = 'travis'
PG_PASS = 'sheeta-pg'


def get_slot_keys_from_db(sample_ids):
    """从数据库获取 sample_id -> slot_key 的映射"""
    import psycopg2
    conn = psycopg2.connect(host=PG_HOST, dbname=PG_DB, user=PG_USER, password=PG_PASS)
    cur = conn.cursor()
    
    mapping = {}
    for sid in sample_ids:
        # sample_id 格式: S001 -> stock_code/year/period 需要从 worksheet 获取
        # 这里直接从 worksheet 的 stock_code/year/period 列查
        pass
    
    cur.close()
    conn.close()
    return mapping


def download_pdf(s3_client, code, slot_key, cache_dir='/tmp/pdf_reextract'):
    """从 rustfs 下载 PDF"""
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, f'{slot_key}.pdf')
    if os.path.exists(local_path):
        return local_path
    
    pdf_key = f'pdf/{code}/{slot_key}.pdf'
    try:
        s3_client.download_file(S3_BUCKET, pdf_key, local_path)
        return local_path
    except Exception as e:
        return None


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    infile = os.path.join(base, 'data', 'stage1b_worksheet.csv')
    
    # 读取 worksheet
    with open(infile, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    
    print(f'总样本: {len(rows)}')
    
    # 初始化 S3 客户端
    s3 = boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
        verify=False
    )
    
    # 统计
    total = len(rows)
    reextracted = 0
    failed = 0
    no_pdf = 0
    improved = 0
    degraded = 0
    
    for i, row in enumerate(rows):
        sid = row['sample_id']
        code = row['stock_code']
        year = row['year']
        period = row['period']
        
        # 构造 slot_key
        period_map = {'annual': '4', 'semi': '2', 'Q1': '1', 'Q3': '3'}
        period_num = period_map.get(period, period)
        slot_key = f'{code}_{year}_{period_num}'
        
        # 下载 PDF
        pdf_path = download_pdf(s3, code, slot_key)
        if not pdf_path:
            no_pdf += 1
            continue
        
        # 重新抽取
        try:
            headings, meta = extract_pdf(pdf_path)
        except Exception as e:
            print(f'  {sid}: extract error: {e}')
            failed += 1
            continue
        
        if headings is None:
            no_pdf += 1
            continue
        
        # 旧结果
        old_headings_str = row.get('pdf_headings', '')
        old_n = len([h for h in old_headings_str.split(' | ') if h.strip()]) if old_headings_str else 0
        
        # 新结果
        new_headings_str = ' | '.join(headings)
        new_n = len(headings)
        
        # 更新行
        row['pdf_headings'] = new_headings_str
        row['pdf_n_headings'] = str(new_n)
        row['pdf_strategy'] = meta.get('strategy', '')
        row['pdf_purity'] = str(meta.get('purity', ''))
        
        reextracted += 1
        
        # 对比改善/退化
        if new_n < old_n and old_n > 20:
            improved += 1
        elif new_n > old_n and new_n > 20:
            degraded += 1
        
        if (i + 1) % 50 == 0:
            print(f'  进度: {i+1}/{total}, 已重抽: {reextracted}, 改善: {improved}, 退化: {degraded}')
    
    # 写回 - 收集所有字段（包括新增的）
    all_fields = set()
    for r in rows:
        all_fields.update(r.keys())
    fieldnames = sorted(all_fields)
    with open(infile, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f'\n完成!')
    print(f'  总样本: {total}')
    print(f'  重抽成功: {reextracted}')
    print(f'  无 PDF: {no_pdf}')
    print(f'  抽取失败: {failed}')
    print(f'  改善 (n_pdf 从 >20 降到 <=20): {improved}')
    print(f'  退化 (n_pdf 从 <=20 升到 >20): {degraded}')
    print(f'  输出: {infile}')


if __name__ == '__main__':
    main()
