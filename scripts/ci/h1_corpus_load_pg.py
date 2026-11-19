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
        --db nooshare_dev --user ci_writer
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


def main():
    parser = argparse.ArgumentParser(description="Load H1 extraction results to PG via psql")
    parser.add_argument("--input", required=True, help="Path to h1-extraction.jsonl")
    parser.add_argument("--host", default="127.0.0.1", help="PG host")
    parser.add_argument("--port", type=int, default=15432, help="PG port")
    parser.add_argument("--db", default="nooshare_dev", help="PG database")
    parser.add_argument("--user", default="ci_writer", help="PG user")
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
        Path(args.emit_sql).write_text(build_sql(valid), encoding="utf-8")
        print(f"SQL_EMIT=PASS path={args.emit_sql} rows={len(valid)}")
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
