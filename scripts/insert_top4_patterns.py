#!/usr/bin/env python3
"""插入前 4 个 pattern 到 h1_pattern_library 表。"""

import hashlib
import json
import re
import psycopg2

PG = dict(
    host='pg.pro.neuralj.com',
    port=5432,
    dbname='nooshare_dev',
    user='travis',
    password='sheeta-pg'
)

# 前 4 个 combo（从 pro 主机读取的精简数据）
COMBOS = [
    {
        "pattern": ["重要提示、目录和释义", "公司简介和主要财务指标", "管理层讨论与分析", "公司治理", "环境和社会责任", "重要事项", "股份变动及股东情况", "优先股相关情况", "债券相关情况", "财务报告"],
        "count": 10858,
        "headings": [
            {"ordinal": 1, "raw_name": "重要提示、目录和释义", "canonical_name": "重要提示、目录和释义"},
            {"ordinal": 2, "raw_name": "公司简介和主要财务指标", "canonical_name": "公司简介和主要财务指标"},
            {"ordinal": 3, "raw_name": "管理层讨论与分析", "canonical_name": "管理层讨论与分析"},
            {"ordinal": 4, "raw_name": "公司治理", "canonical_name": "公司治理、环境和社会"},
            {"ordinal": 5, "raw_name": "环境和社会责任", "canonical_name": "环境和社会责任"},
            {"ordinal": 6, "raw_name": "重要事项", "canonical_name": "重要事项"},
            {"ordinal": 7, "raw_name": "股份变动及股东情况", "canonical_name": "股份变动及股东情况"},
            {"ordinal": 8, "raw_name": "优先股相关情况", "canonical_name": "优先股相关情况"},
            {"ordinal": 9, "raw_name": "债券相关情况", "canonical_name": "债券相关情况"},
            {"ordinal": 10, "raw_name": "财务报告", "canonical_name": "财务报告"}
        ]
    },
    {
        "pattern": ["释义", "公司简介和主要财务指标", "管理层讨论与分析", "公司治理", "环境与社会责任", "重要事项", "股份变动及股东情况", "优先股相关情况", "债券相关情况", "财务报告"],
        "count": 10019,
        "headings": [
            {"ordinal": 1, "raw_name": "释义", "canonical_name": ""},
            {"ordinal": 2, "raw_name": "公司简介和主要财务指标", "canonical_name": "公司简介和主要财务指标"},
            {"ordinal": 3, "raw_name": "管理层讨论与分析", "canonical_name": "管理层讨论与分析"},
            {"ordinal": 4, "raw_name": "公司治理", "canonical_name": "公司治理、环境和社会"},
            {"ordinal": 5, "raw_name": "环境与社会责任", "canonical_name": ""},
            {"ordinal": 6, "raw_name": "重要事项", "canonical_name": "重要事项"},
            {"ordinal": 7, "raw_name": "股份变动及股东情况", "canonical_name": "股份变动及股东情况"},
            {"ordinal": 8, "raw_name": "优先股相关情况", "canonical_name": "优先股相关情况"},
            {"ordinal": 9, "raw_name": "债券相关情况", "canonical_name": "债券相关情况"},
            {"ordinal": 10, "raw_name": "财务报告", "canonical_name": "财务报告"}
        ]
    },
    {
        "pattern": ["释义", "公司简介和主要财务指标", "管理层讨论与分析", "公司治理、环境和社会", "重要事项", "股份变动及股东情况", "债券相关情况", "财务报告"],
        "count": 5430,
        "headings": [
            {"ordinal": 1, "raw_name": "释义", "canonical_name": ""},
            {"ordinal": 2, "raw_name": "公司简介和主要财务指标", "canonical_name": "公司简介和主要财务指标"},
            {"ordinal": 3, "raw_name": "管理层讨论与分析", "canonical_name": "管理层讨论与分析"},
            {"ordinal": 4, "raw_name": "公司治理、环境和社会", "canonical_name": "公司治理、环境和社会"},
            {"ordinal": 5, "raw_name": "重要事项", "canonical_name": "重要事项"},
            {"ordinal": 6, "raw_name": "股份变动及股东情况", "canonical_name": "股份变动及股东情况"},
            {"ordinal": 7, "raw_name": "债券相关情况", "canonical_name": "债券相关情况"},
            {"ordinal": 8, "raw_name": "财务报告", "canonical_name": "财务报告"}
        ]
    },
    {
        "pattern": ["重要提示、目录和释义", "公司简介和主要财务指标", "公司业务概要", "经营情况讨论与分析", "重要事项", "股份变动及股东情况", "优先股相关情况", "董事、监事、高级管理人员和员工情况", "公司治理", "公司债券相关情况", "财务报告", "备查文件目录"],
        "count": 4196,
        "headings": [
            {"ordinal": 1, "raw_name": "重要提示、目录和释义", "canonical_name": "重要提示、目录和释义"},
            {"ordinal": 2, "raw_name": "公司简介和主要财务指标", "canonical_name": "公司简介和主要财务指标"},
            {"ordinal": 3, "raw_name": "公司业务概要", "canonical_name": "公司业务概要"},
            {"ordinal": 4, "raw_name": "经营情况讨论与分析", "canonical_name": "经营情况讨论与分析"},
            {"ordinal": 5, "raw_name": "重要事项", "canonical_name": "重要事项"},
            {"ordinal": 6, "raw_name": "股份变动及股东情况", "canonical_name": "股份变动及股东情况"},
            {"ordinal": 7, "raw_name": "优先股相关情况", "canonical_name": "优先股相关情况"},
            {"ordinal": 8, "raw_name": "董事、监事、高级管理人员和员工情况", "canonical_name": "董事、监事、高级管理人员和员工情况"},
            {"ordinal": 9, "raw_name": "公司治理", "canonical_name": "公司治理、环境和社会"},
            {"ordinal": 10, "raw_name": "公司债券相关情况", "canonical_name": "公司债券相关情况"},
            {"ordinal": 11, "raw_name": "财务报告", "canonical_name": "财务报告"},
            {"ordinal": 12, "raw_name": "备查文件目录", "canonical_name": "备查文件目录"}
        ]
    }
]

def _normalize_heading(text):
    """去除章节标记前缀，与 pattern_matcher.py 保持一致。"""
    text = re.sub(r'^(第[一二三四五六七八九十百零\d]+[章节部分])\s*', '', text.strip())
    return text.strip()

def compute_pattern_hash(pattern):
    """计算 pattern 的 SHA256 哈希。与 pattern_matcher.py 使用相同算法。"""
    normalized = [_normalize_heading(t) for t in pattern]
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()

def main():
    print("连接 PostgreSQL...")
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    
    print("插入前 4 个 pattern...")
    for i, combo in enumerate(COMBOS, 1):
        pattern_hash = compute_pattern_hash(combo["pattern"])
        pattern = combo["pattern"]
        count = combo["count"]
        headings = json.dumps(combo["headings"], ensure_ascii=False)
        
        cur.execute("""
            INSERT INTO annual_semi.h1_pattern_library (pattern_hash, pattern, count, headings)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (pattern_hash) DO NOTHING
            RETURNING id
        """, (pattern_hash, pattern, count, headings))
        
        result = cur.fetchone()
        if result:
            print(f"  ✅ Pattern {i}: id={result[0]}, count={count}, hash={pattern_hash[:16]}...")
        else:
            print(f"  ⏭️  Pattern {i}: 已存在，跳过")
    
    conn.commit()
    
    # 验证
    print("\n验证插入结果...")
    cur.execute("""
        SELECT id, pattern_hash, count, jsonb_array_length(headings) as n_headings
        FROM annual_semi.h1_pattern_library
        ORDER BY count DESC
    """)
    rows = cur.fetchall()
    
    print(f"\n表中共 {len(rows)} 条记录：")
    for id_, hash_, count, n_headings in rows:
        print(f"  id={id_}, count={count}, n_headings={n_headings}, hash={hash_[:16]}...")
    
    cur.close()
    conn.close()
    print("\n✅ 插入完成")

if __name__ == '__main__':
    main()
