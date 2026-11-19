#!/usr/bin/env python3
"""
H1 提取结果加载器：读取 h1-extraction.jsonl，写入 PG 数据库。

表结构：annual_semi.h1_corpus_results
- slot_key (PK): 语料槽位键（如 000001_2003_2）
- stock_code: 股票代码
- report_year: 报告年份
- period: 报告期（1=年报, 2=半年报）
- source_sha256: 源文件 SHA256
- n_bytes: 源文件大小
- extraction_method: 抽取方法（ch_zh / ch_en / ...）
- n_headings: 识别到的标题数
- ordinal_valid: 序号校验是否通过
- ordinal_verdict: 序号校验结论（PASS / FAIL_...）
- is_complete_l1: 是否为完整 L1 结构
- coverage_ratio: 标准模板覆盖率
- headings_json: 标题详情（JSONB）
- missing_always_sections: 缺失的必选章节（数组）
- missing_conditional_sections: 缺失的条件章节（数组）
- reg_version: 参考的法规版本
- loaded_at: 加载时间戳

用法：
    python scripts/ci/h1_corpus_load_pg.py \
        --input h1-extraction.jsonl \
        --host 127.0.0.1 --port 15432 \
        --db nooshare_dev --user ci_probe
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json


DDL = """
CREATE SCHEMA IF NOT EXISTS annual_semi;

CREATE TABLE IF NOT EXISTS annual_semi.h1_corpus_results (
    slot_key TEXT PRIMARY KEY,
    stock_code TEXT NOT NULL,
    report_year INTEGER NOT NULL,
    period INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    n_bytes BIGINT NOT NULL,
    extraction_method TEXT,
    n_headings INTEGER,
    ordinal_valid BOOLEAN,
    ordinal_verdict TEXT,
    is_complete_l1 BOOLEAN,
    coverage_ratio DOUBLE PRECISION,
    headings_json JSONB,
    missing_always_sections INTEGER[],
    missing_conditional_sections INTEGER[],
    reg_version TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_h1_corpus_stock_year
    ON annual_semi.h1_corpus_results (stock_code, report_year, period);
"""


def load_pg(
    input_path: Path,
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> dict:
    """读取 JSONL 并写入 PG，返回统计摘要。"""
    records = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        return {"loaded": 0, "skipped": 0, "total": 0, "error": "empty input"}

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=password,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            # 建表
            cur.execute(DDL)
            conn.commit()

            loaded = 0
            skipped = 0
            now = datetime.now(timezone.utc)

            for rec in records:
                slot_key = rec.get("slot_key")
                if not slot_key:
                    skipped += 1
                    continue

                headings_json = Json(rec.get("headings", []))
                missing_always = rec.get("missing_always_sections") or []
                missing_conditional = rec.get("missing_conditional_sections") or []

                cur.execute(
                    """
                    INSERT INTO annual_semi.h1_corpus_results (
                        slot_key, stock_code, report_year, period,
                        source_sha256, n_bytes, extraction_method,
                        n_headings, ordinal_valid, ordinal_verdict,
                        is_complete_l1, coverage_ratio, headings_json,
                        missing_always_sections, missing_conditional_sections,
                        reg_version, loaded_at
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (slot_key) DO UPDATE SET
                        stock_code = EXCLUDED.stock_code,
                        report_year = EXCLUDED.report_year,
                        period = EXCLUDED.period,
                        source_sha256 = EXCLUDED.source_sha256,
                        n_bytes = EXCLUDED.n_bytes,
                        extraction_method = EXCLUDED.extraction_method,
                        n_headings = EXCLUDED.n_headings,
                        ordinal_valid = EXCLUDED.ordinal_valid,
                        ordinal_verdict = EXCLUDED.ordinal_verdict,
                        is_complete_l1 = EXCLUDED.is_complete_l1,
                        coverage_ratio = EXCLUDED.coverage_ratio,
                        headings_json = EXCLUDED.headings_json,
                        missing_always_sections = EXCLUDED.missing_always_sections,
                        missing_conditional_sections = EXCLUDED.missing_conditional_sections,
                        reg_version = EXCLUDED.reg_version,
                        loaded_at = EXCLUDED.loaded_at
                    """,
                    (
                        slot_key,
                        rec.get("stock_code"),
                        rec.get("report_year"),
                        rec.get("period"),
                        rec.get("source_sha256"),
                        rec.get("n_bytes"),
                        rec.get("extraction_method"),
                        rec.get("n_headings"),
                        rec.get("ordinal_valid"),
                        rec.get("ordinal_verdict"),
                        rec.get("is_complete_l1"),
                        rec.get("coverage_ratio"),
                        headings_json,
                        missing_always,
                        missing_conditional,
                        rec.get("reg_version"),
                        now,
                    ),
                )
                loaded += 1

            conn.commit()
            return {
                "loaded": loaded,
                "skipped": skipped,
                "total": len(records),
            }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Load H1 extraction results to PG")
    parser.add_argument("--input", required=True, help="Path to h1-extraction.jsonl")
    parser.add_argument("--host", default="127.0.0.1", help="PG host")
    parser.add_argument("--port", type=int, default=15432, help="PG port")
    parser.add_argument("--db", default="nooshare_dev", help="PG database")
    parser.add_argument("--user", default="ci_probe", help="PG user")
    parser.add_argument(
        "--password",
        default=os.environ.get("PG_PASSWORD", ""),
        help="PG password (or set PG_PASSWORD env var)",
    )
    args = parser.parse_args()

    if not args.password:
        print("PG_LOAD=FAIL code=PG_SECRET_MISSING", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"PG_LOAD=FAIL code=INPUT_MISSING path={input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        result = load_pg(
            input_path=input_path,
            host=args.host,
            port=args.port,
            db=args.db,
            user=args.user,
            password=args.password,
        )
        print(f"PG_LOAD=PASS loaded={result['loaded']} skipped={result['skipped']} total={result['total']}")
    except Exception as e:
        # 不回显原始错误（可能含连接信息）
        code = "PG_LOAD_ERROR"
        if "password authentication" in str(e).lower():
            code = "PG_AUTH_FAIL"
        elif "connection refused" in str(e).lower():
            code = "PG_TCP_REFUSED"
        elif "timeout" in str(e).lower():
            code = "PG_CONN_TIMEOUT"
        print(f"PG_LOAD=FAIL code={code}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
