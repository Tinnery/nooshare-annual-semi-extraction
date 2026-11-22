"""权威报告列表：从共享 PG 的 annual_semi.reconciled_report 读取裁决后的报告清单。

背景：
    extraction 原本直接枚举 RustFS published/ 前缀作为待处理清单，会带入未进入
    reconciled_report 裁决的孤儿文件。nooshare-annual-semi 的 reconciled_report
    是「股票 × 年份 × 期次」的胜者真相源，作为报告列表更权威。

职责边界（窄）：
    - 只读：仅 SELECT reconciled_report，不写任何表。
    - 不连 S3：只产出清单记录，不下载语料。
    - 连接走 psql 子进程：CI 隧道上 psycopg2 内置 libpq 会断连，系统 psql 可用
      （与 h1_corpus_load_pg.py / pattern_matcher.py 一致）。
    - 不回显异常文本：可能含 endpoint/凭据线索，只返回固定错误码。

清单字段：
    slot_key     : <code>_<year>_<period>，与 S3 published key 的文件名部分一致
    s3_key       : published/<code>/<code>_<year>_<period>.md
    stock_code   : 6 位股票代码
    report_year  : 报告年份
    period       : 2=半年报, 4=年报
    winner_md_path: reconciled_report 记录的胜者路径（供审计，不作为下载键）
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, asdict
from typing import Optional

# 报告清单的权威表（schema 显式限定，避免 search_path 差异）
REPORT_TABLE = "annual_semi.reconciled_report"

# 只接受年报/半年报（与 S3 published key 的 [24] 命名一致）
VALID_PERIODS = (2, 4)


@dataclass(frozen=True)
class ReportSlot:
    slot_key: str
    s3_key: str
    stock_code: str
    report_year: int
    period: int
    winner_md_path: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_query(start_year: int) -> str:
    """构造只读查询 SQL。start_year 为 int（调用方已强转），无注入面。"""
    periods = ",".join(str(p) for p in VALID_PERIODS)
    return (
        "SELECT stock_code, report_year, period, winner_md_path "
        f"FROM {REPORT_TABLE} "
        f"WHERE report_year >= {int(start_year)} AND period IN ({periods}) "
        "ORDER BY stock_code, report_year, period"
    )


def slot_from_row(line: str) -> Optional[ReportSlot]:
    """解析 psql tuples-only 输出的一行（字段分隔符 |）。

    winner_md_path 可能含 |，用 split('|', 3) 保留尾部完整路径。
    """
    parts = line.rstrip("\n").split("|", 3)
    if len(parts) != 4:
        return None
    code, year_s, period_s, path = (p.strip() for p in parts)
    if not code or not year_s.isdigit() or not period_s.isdigit():
        return None
    year = int(year_s)
    period = int(period_s)
    if period not in VALID_PERIODS:
        return None
    slot_key = f"{code}_{year}_{period}"
    return ReportSlot(
        slot_key=slot_key,
        s3_key=f"published/{code}/{slot_key}.md",
        stock_code=code,
        report_year=year,
        period=period,
        winner_md_path=path,
    )


def load_report_list(
    *,
    start_year: int,
    host: str,
    port: str,
    dbname: str,
    user: str,
    password: str,
    psql_bin: str = "psql",
    timeout: int = 120,
) -> tuple[Optional[list[ReportSlot]], Optional[str]]:
    """读取报告列表。成功返回 (slots, None)；失败返回 (None, 固定错误码)。

    错误码（不回显异常文本）：
        REPORT_LIST_NO_PSQL   : psql 不可用
        REPORT_LIST_TIMEOUT   : 查询超时
        REPORT_LIST_PG_FAIL   : psql 非零退出（连接/权限/SQL 错误）
        REPORT_LIST_BAD_ROWS  : 输出行解析失败率过高
    """
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    cmd = [
        psql_bin, "-h", host, "-p", str(port), "-U", user, "-d", dbname,
        "--no-psqlrc", "--tuples-only", "--field-separator=|",
        "-v", "ON_ERROR_STOP=1", "-c", build_query(start_year),
    ]
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        return None, "REPORT_LIST_NO_PSQL"
    except subprocess.TimeoutExpired:
        return None, "REPORT_LIST_TIMEOUT"
    except Exception:
        return None, "REPORT_LIST_PG_FAIL"

    if result.returncode != 0:
        return None, "REPORT_LIST_PG_FAIL"

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    slots: list[ReportSlot] = []
    bad = 0
    for line in lines:
        slot = slot_from_row(line)
        if slot is None:
            bad += 1
        else:
            slots.append(slot)
    # 容忍个别异常行（如 winner_md_path 含换行），但异常占比过高视为数据污染
    if lines and bad / len(lines) > 0.01:
        return None, "REPORT_LIST_BAD_ROWS"
    return slots, None


def load_report_list_from_env(start_year: int, *, timeout: int = 120):
    """从 CI 注入的 PG_* 环境变量读取列表（隧道本地端口）。"""
    return load_report_list(
        start_year=start_year,
        host=os.environ.get("PG_HOST_LOCAL", "127.0.0.1"),
        port=os.environ.get("PG_PORT_LOCAL", "15432"),
        dbname=os.environ.get("PG_NAME", "nooshare_dev"),
        user=os.environ.get("PG_USER", "ci"),
        password=os.environ.get("PG_PASSWORD", ""),
        timeout=timeout,
    )
