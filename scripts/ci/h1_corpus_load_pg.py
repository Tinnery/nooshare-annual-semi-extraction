#!/usr/bin/env python3
"""
H1 提取结果加载器：读取 h1-extraction.jsonl，经 psql 写入 PG 数据库。

为什么用 psql 而非 psycopg2：
    CI 经 stunnel + PSK 隧道连 PG。实测 psycopg2-binary 内置 libpq 在该隧道上
    报 "server closed the connection unexpectedly"，而系统 psql 可正常连接
    （PG_DIAG_PSQL_AFTER_REBUILD=PASS）。故改用 psql 子进程，绕开客户端库兼容性问题。

表结构由 scripts/ci/sql/h1_corpus_results.sql 预建（DEV 库一次性 DDL）。
本脚本只负责写数据（INSERT ... ON CONFLICT DO UPDATE），不建表。

用法：
    python scripts/ci/h1_corpus_load_pg.py \
        --input h1-extraction.jsonl \
        --host 127.0.0.1 --port 15432 \
        --db nooshare_dev --user ci
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def quote_literal(value: Any) -> str:
    """把 Python 值转为 PG SQL 字面量。字符串内单引号翻倍转义。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    # 字符串 / 已序列化的 JSON：转义单引号
    return "'" + str(value).replace("'", "''") + "'"


def json_literal(value: Any) -> str:
    """把对象序列化为 JSON 文本字面量（用于 ::jsonb 列）。"""
    if value is None:
        return "NULL::jsonb"
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return quote_literal(text) + "::jsonb"


def int_array_literal(values: Any) -> str:
    """把整数列表转为 PG integer[] 字面量；None 保留 SQL NULL 语义。"""
    if values is None:
        return "NULL::integer[]"
    if not values:
        return "ARRAY[]::integer[]"
    items = ",".join(str(int(v)) for v in values)
    return quote_literal("{" + items + "}") + "::integer[]"


def build_sql(records: list[dict]) -> str:
    """生成整批 UPSERT SQL（单事务，逐行 INSERT ... ON CONFLICT）。"""
    lines = ["BEGIN;"]
    for rec in records:
        slot_key = rec.get("slot_key")
        if not slot_key:
            continue
        cols = (
            "slot_key, stock_code, report_year, period, "
            "source_sha256, n_bytes, extraction_method, n_headings, "
            "ordinal_valid, ordinal_verdict, is_complete_l1, coverage_ratio, "
            "headings_json, missing_always_sections, missing_conditional_sections, "
            "reg_version, loaded_at"
        )
        vals = ",".join(
            [
                quote_literal(slot_key),
                quote_literal(rec.get("stock_code")),
                quote_literal(rec.get("report_year")),
                quote_literal(rec.get("period")),
                quote_literal(rec.get("source_sha256")),
                quote_literal(rec.get("n_bytes")),
                quote_literal(rec.get("extraction_method")),
                quote_literal(rec.get("n_headings")),
                quote_literal(rec.get("ordinal_valid")),
                quote_literal(rec.get("ordinal_verdict")),
                quote_literal(rec.get("is_complete_l1")),
                quote_literal(rec.get("coverage_ratio")),
                json_literal(rec.get("headings", [])),
                int_array_literal(rec.get("missing_always_sections")),
                int_array_literal(rec.get("missing_conditional_sections")),
                quote_literal(rec.get("reg_version")),
                "NOW()",
            ]
        )
        lines.append(
            f"INSERT INTO annual_semi.h1_corpus_results ({cols}) VALUES ({vals}) "
            f"ON CONFLICT (slot_key) DO UPDATE SET "
            f"stock_code=EXCLUDED.stock_code, report_year=EXCLUDED.report_year, "
            f"period=EXCLUDED.period, source_sha256=EXCLUDED.source_sha256, "
            f"n_bytes=EXCLUDED.n_bytes, extraction_method=EXCLUDED.extraction_method, "
            f"n_headings=EXCLUDED.n_headings, ordinal_valid=EXCLUDED.ordinal_valid, "
            f"ordinal_verdict=EXCLUDED.ordinal_verdict, is_complete_l1=EXCLUDED.is_complete_l1, "
            f"coverage_ratio=EXCLUDED.coverage_ratio, headings_json=EXCLUDED.headings_json, "
            f"missing_always_sections=EXCLUDED.missing_always_sections, "
            f"missing_conditional_sections=EXCLUDED.missing_conditional_sections, "
            f"reg_version=EXCLUDED.reg_version, loaded_at=EXCLUDED.loaded_at;"
        )
    lines.append("COMMIT;")
    return "\n".join(lines)


def load_pg(
    input_path: Path,
    host: str,
    port: int,
    db: str,
    user: str,
    password: str,
) -> dict:
    """读取 JSONL，生成 SQL，经 psql 子进程写入 PG。"""
    records = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    total = len(records)
    if not records:
        return {"loaded": 0, "skipped": 0, "total": 0}

    valid = [r for r in records if r.get("slot_key")]
    skipped = total - len(valid)

    sql = build_sql(valid)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(sql)
        tmp_path = tmp.name

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        "psql",
        "-h", host,
        "-p", str(port),
        "-U", user,
        "-d", db,
        "-v", "ON_ERROR_STOP=1",
        "-f", tmp_path,
    ]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=120
        )
    except FileNotFoundError:
        print("PG_LOAD=FAIL code=PSQL_NOT_FOUND", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    if proc.returncode != 0:
        # 诊断：输出 psql stderr 供定位（trust 认证无密码；仅取前若干行并截断）
        diag = "\n".join(proc.stderr.strip().splitlines()[:8])
        print(f"PG_PSQL_STDERR={diag[:1200]}", file=sys.stderr)
        # 映射为固定错误码
        err = proc.stderr.lower()
        code = "PG_LOAD_ERROR"
        if "authentication" in err:
            code = "PG_AUTH_FAIL"
        elif "permission denied" in err:
            code = "PG_PERM_DENIED"
        elif "connection refused" in err or "could not connect" in err:
            code = "PG_TCP_REFUSED"
        elif "relation" in err and "does not exist" in err:
            code = "PG_TABLE_MISSING"
        elif "syntax error" in err:
            code = "PG_SQL_SYNTAX"
        print(f"PG_LOAD=FAIL code={code}", file=sys.stderr)
        sys.exit(1)

    return {"loaded": len(valid), "skipped": skipped, "total": total}


def emit_key_map(records: list[dict], output_path: Path) -> None:
    """生成批次 key 映射文件（row_no, slot_key, source_sha256）。
    
    用于失败时上传，精确定位到具体记录。由同一组 valid records 生成，
    保证与 SQL/CSV 一一对应。row_no 从 1 开始（批次内记录序号）。
    """
    with output_path.open("w", encoding="utf-8") as f:
        for i, rec in enumerate(records, start=1):
            f.write(json.dumps({
                "row_no": i,
                "slot_key": rec.get("slot_key"),
                "source_sha256": rec.get("source_sha256"),
            }, ensure_ascii=False) + "\n")


def emit_csv_mode(records: list[dict], csv_path: Path, sql_path: Path) -> None:
    """生成 CSV 数据文件 + SQL 脚本（COPY staging 模式）。
    
    性能优化：COPY 批量加载到临时表，然后一条 INSERT ON CONFLICT merge。
    把 19 分钟抖动窗口压到秒级，与 P0 链路韧性协同。
    """
    import csv
    
    columns = [
        "slot_key", "stock_code", "report_year", "period",
        "source_sha256", "n_bytes", "extraction_method", "n_headings",
        "ordinal_valid", "ordinal_verdict", "is_complete_l1", "coverage_ratio",
        "headings_json", "missing_always_sections", "missing_conditional_sections",
        "reg_version",
    ]
    
    def format_value(col: str, val: Any) -> Any:
        if val is None:
            return None  # NULL
        if col == "headings_json":
            return json.dumps(val, ensure_ascii=False, separators=(",", ":"))
        if col in ("missing_always_sections", "missing_conditional_sections"):
            if not val:
                return "{}"
            return "{" + ",".join(str(int(v)) for v in val) + "}"
        return val
    
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for rec in records:
            row = [format_value(col, rec.get(col)) for col in columns]
            writer.writerow(row)
    
    csv_escaped = str(csv_path).replace("'", "''")
    col_list = ", ".join(columns)
    
    update_cols = [c for c in columns if c != "slot_key"]
    update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
    update_set += ", loaded_at=EXCLUDED.loaded_at"
    
    insert_cols = col_list + ", loaded_at"
    select_cols = col_list + ", NOW()"
    
    sql = f"""BEGIN;
CREATE TEMP TABLE h1_staging (
  slot_key TEXT,
  stock_code TEXT,
  report_year INTEGER,
  period INTEGER,
  source_sha256 TEXT,
  n_bytes BIGINT,
  extraction_method TEXT,
  n_headings INTEGER,
  ordinal_valid BOOLEAN,
  ordinal_verdict TEXT,
  is_complete_l1 BOOLEAN,
  coverage_ratio DOUBLE PRECISION,
  headings_json JSONB,
  missing_always_sections INTEGER[],
  missing_conditional_sections INTEGER[],
  reg_version TEXT
);
\\copy h1_staging ({col_list}) FROM '{csv_escaped}' WITH (FORMAT csv, HEADER false);
INSERT INTO annual_semi.h1_corpus_results ({insert_cols})
SELECT {select_cols} FROM h1_staging
ON CONFLICT (slot_key) DO UPDATE SET {update_set};
DROP TABLE h1_staging;
COMMIT;
"""
    sql_path.write_text(sql, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Load H1 extraction results to PG via psql")
    parser.add_argument("--input", required=True, help="Path to h1-extraction.jsonl")
    parser.add_argument("--host", default="127.0.0.1", help="PG host")
    parser.add_argument("--port", type=int, default=15432, help="PG port")
    parser.add_argument("--db", default="nooshare_dev", help="PG database")
    parser.add_argument("--user", default="ci", help="PG user")
    parser.add_argument(
        "--password",
        default=os.environ.get("PG_PASSWORD", ""),
        help="PG password (or set PG_PASSWORD env var; unused under trust auth)",
    )
    parser.add_argument(
        "--emit-sql",
        metavar="PATH",
        help="只生成 UPSERT SQL 到指定文件并返回，不连接 PG（供 shell 直接调 psql -f）",
    )
    parser.add_argument(
        "--emit-csv",
        metavar="SQL_PATH",
        help="生成 CSV 数据文件 + SQL 脚本（COPY staging 模式）。"
             "SQL_PATH 为 SQL 文件路径，CSV 文件自动生成同目录同名 .csv。",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"PG_LOAD=FAIL code=INPUT_MISSING path={input_path}", file=sys.stderr)
        sys.exit(1)

    # --emit-sql 模式：只生成 SQL，不连 PG。避免 uv run python 子进程的 libpq 环境影响 psql。
    if args.emit_sql:
        with input_path.open("r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        valid = [r for r in records if r.get("slot_key")]
        sql_path = Path(args.emit_sql)
        sql_path.write_text(build_sql(valid), encoding="utf-8")
        # 同步生成 key map（供失败时上传定位）
        key_map_path = sql_path.with_suffix(".key-map.jsonl")
        emit_key_map(valid, key_map_path)
        print(f"SQL_EMIT=PASS path={sql_path} key_map={key_map_path} rows={len(valid)}")
        return

    # --emit-csv 模式：生成 CSV + SQL（COPY staging 模式），性能优化。
    if args.emit_csv:
        sql_path = Path(args.emit_csv)
        csv_path = sql_path.with_suffix(".csv")
        with input_path.open("r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        valid = [r for r in records if r.get("slot_key")]
        emit_csv_mode(valid, csv_path, sql_path)
        # 同步生成 key map（供失败时上传定位）
        key_map_path = sql_path.with_suffix(".key-map.jsonl")
        emit_key_map(valid, key_map_path)
        print(f"CSV_EMIT=PASS sql={sql_path} csv={csv_path} key_map={key_map_path} rows={len(valid)}")
        return

    result = load_pg(
        input_path=input_path,
        host=args.host,
        port=args.port,
        db=args.db,
        user=args.user,
        password=args.password,
    )
    print(
        f"PG_LOAD=PASS loaded={result['loaded']} "
        f"skipped={result['skipped']} total={result['total']}"
    )


if __name__ == "__main__":
    main()
