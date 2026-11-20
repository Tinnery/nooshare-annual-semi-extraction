#!/usr/bin/env python3
"""创建 h1_pattern_library 表（只建表，不导入数据）。"""

import psycopg2

PG = dict(
    host='pg.pro.neuralj.com',
    port=5432,
    dbname='nooshare_dev',
    user='travis',
    password='sheeta-pg'
)

DDL = """
CREATE TABLE IF NOT EXISTS annual_semi.h1_pattern_library (
    id SERIAL PRIMARY KEY,
    pattern_hash VARCHAR(64) UNIQUE NOT NULL,
    pattern TEXT[] NOT NULL,
    count INT NOT NULL,
    headings JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_h1_pattern_hash ON annual_semi.h1_pattern_library(pattern_hash);
CREATE INDEX IF NOT EXISTS idx_h1_count ON annual_semi.h1_pattern_library(count DESC);
"""

def main():
    print("连接 PostgreSQL...")
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    
    print("执行 DDL...")
    cur.execute(DDL)
    conn.commit()
    
    print("验证表结构...")
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'annual_semi' AND table_name = 'h1_pattern_library'
        ORDER BY ordinal_position
    """)
    rows = cur.fetchall()
    
    print("\n表结构：")
    for col, dtype, nullable in rows:
        print(f"  {col:20s} {dtype:20s} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
    
    cur.close()
    conn.close()
    print("\n✅ 表创建成功：annual_semi.h1_pattern_library")

if __name__ == '__main__':
    main()
