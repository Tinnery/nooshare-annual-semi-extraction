"""H2（二级标题）模板库加载与匹配。

权威来源：PostgreSQL `annual_semi.h2_pattern_library`
（由 nooshare-annual-semi/scripts/build_h2_pattern_library.py 构建，
v2 起只收录通过标题性校验且 count >= 阈值的模板）。

加载优先级（与 h1/pattern_matcher 一致的三层设计）：
1. 显式注入的 entries（单元测试 mock 通道）
2. 环境变量配置的 PG 连接（psql 子进程——CI 隧道上 psycopg2 内置
   libpq 会断连，系统 psql 可用，与 h1_corpus_load_pg.py 一致）
3. 均未配置或连接失败 → 空库降级（lookup 恒 None，不阻断抽取）

安全约定（与 report_list.py 一致）：
- 异常不回显文本（可能含 endpoint/凭据线索），只记固定错误码。
- psql 输出按行解析，畸形行跳过。

归一化一致性（重要）：
    normalize_for_match 必须与上游构建脚本 normalize_heading 保持同一
    语义：去末尾标点、删除全部空白、循环剥离前导序号。上游改归一化时
    必须同步改这里，否则库内 heading_normalized 与候选文本对不上。

匹配语义：
- exact        ：归一化后与库内模板完全一致
- glued_prefix ：候选以某个库模板开头，剩余部分不含汉字（粘上了
   数字/符号噪声，如「货币资金4,342,156.00」→「货币资金」）
- 其余（含截断、含汉字粘连的变体标题）一律不匹配，宁缺毋滥。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

# 模板库表（schema 固定，与上游构建脚本一致）
LIBRARY_TABLE = "annual_semi.h2_pattern_library"

# 只读查询的默认参数
DEFAULT_MIN_COUNT = 10
DEFAULT_LEVELS = (2,)

# ---- 归一化（与上游构建脚本同语义） ----
RE_CJK = re.compile(r"[\u4e00-\u9fff]")
RE_TRAIL_PUNCT = re.compile(r"[：:．.。、，,；;！!？?]+$")
RE_LEAD_ARABIC = re.compile(r"^\d+\s*[、.．，,：:]")
RE_LEAD_CN_PAREN = re.compile(r"^[（(]\s*[一二三四五六七八九十百]+\s*[）)]")
RE_LEAD_ARABIC_PAREN = re.compile(r"^[（(]\s*\d+\s*[）)]")
RE_LEAD_CN_DUN = re.compile(r"^[一二三四五六七八九十百]+\s*、")


def normalize_for_match(text: str) -> str:
    """候选标题归一化（与上游构建脚本 normalize_heading 同语义）。"""
    if not text:
        return ""
    s = text.strip()
    s = RE_TRAIL_PUNCT.sub("", s)
    s = re.sub(r"\s+", "", s)
    for _ in range(3):
        before = s
        s = RE_LEAD_ARABIC.sub("", s)
        s = RE_LEAD_CN_PAREN.sub("", s)
        s = RE_LEAD_ARABIC_PAREN.sub("", s)
        s = RE_LEAD_CN_DUN.sub("", s)
        if s == before:
            break
    return s.strip()


class H2PatternLibrary:
    """二级标题模板库：加载 + 精确/粘连匹配。

    库来源优先级：显式注入 > PG 环境变量 > 空库降级。
    """

    def __init__(self, entries: Optional[list[dict]] = None):
        self._by_norm: dict[str, dict] = {}
        self._loaded = False
        self._load_error: Optional[str] = None
        self._injected = entries

    def _ingest(self, entries: list[dict]) -> None:
        for e in entries:
            norm = (e.get("heading_normalized") or "").strip()
            if not norm:
                continue
            self._by_norm[norm] = {
                "heading_normalized": norm,
                "heading_raw": (e.get("heading_raw") or norm).strip(),
                "heading_level": e.get("heading_level"),
                "count": int(e.get("count") or 0),
                "stability_score": e.get("stability_score"),
            }

    def _load(self) -> None:
        """懒加载：注入通道 > PG 环境变量 > 空库降级。"""
        if self._loaded:
            return

        if self._injected is not None:
            self._ingest(self._injected)
            self._loaded = True
            print(f"H2_PATTERN_LIB=PASS source=injected n={len(self._by_norm)}")
            return

        host = os.environ.get("PG_HOST", "").strip()
        if not host:
            self._load_error = "H2_LIB_NO_PG_ENV"
            self._loaded = True
            print(f"H2_PATTERN_LIB=DEGRADED code={self._load_error}")
            return

        rows, err = _psql_fetch(
            host=host,
            port=os.environ.get("PG_PORT", "5432").strip(),
            dbname=os.environ.get("PG_NAME", "").strip(),
            user=os.environ.get("PG_USER", "").strip(),
            password=os.environ.get("PG_PASSWORD", ""),
            min_count=_env_int("H2_PATTERN_MIN_COUNT", DEFAULT_MIN_COUNT),
            levels=_env_levels("H2_PATTERN_LEVELS", DEFAULT_LEVELS),
        )
        if err:
            self._load_error = err
            self._loaded = True
            print(f"H2_PATTERN_LIB=DEGRADED code={err}")
            return

        self._ingest(rows)
        self._loaded = True
        print(f"H2_PATTERN_LIB=PASS source=pg n={len(self._by_norm)}")

    def lookup(self, raw: str) -> Optional[dict]:
        """候选标题查库。命中返回库记录（含 relation），未命中 None。"""
        self._load()
        norm = normalize_for_match(raw)
        if not norm:
            return None

        hit = self._by_norm.get(norm)
        if hit:
            return {**hit, "relation": "exact", "candidate_normalized": norm}

        # 粘连噪声：候选以某库模板开头，剩余部分不含汉字
        glued = self._find_glued(norm)
        if glued:
            prefix, rec = glued
            return {**rec, "relation": "glued_prefix", "candidate_normalized": norm}
        return None

    def _find_glued(self, norm: str) -> Optional[tuple[str, dict]]:
        """找最长的「库内前缀 + 无汉字残余」。"""
        for i in range(len(norm) - 1, 1, -1):
            rest = norm[i:]
            if RE_CJK.search(rest):
                continue
            rec = self._by_norm.get(norm[:i])
            if rec:
                return (norm[:i], rec)
        return None

    @property
    def title_count(self) -> int:
        """库内模板词条数（供 fail-fast / 诊断）。"""
        self._load()
        return len(self._by_norm)

    @property
    def load_error(self) -> Optional[str]:
        """固定错误码（无异常文本），None = 加载成功。"""
        return self._load_error


# ---- 单例（运行时共用一次加载结果） ----
_INSTANCE: Optional[H2PatternLibrary] = None


def get_h2_library() -> H2PatternLibrary:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = H2PatternLibrary()
    return _INSTANCE


def reset_h2_library() -> None:
    """重置单例（测试用：环境变量变化后强制重载）。"""
    global _INSTANCE
    _INSTANCE = None


# ---- psql 拉取（隧道约束：不用 psycopg2） ----
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_levels(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        vals = tuple(int(x) for x in raw.split(",") if x.strip())
        return vals or default
    except ValueError:
        return default


def _psql_fetch(
    *,
    host: str,
    port: str,
    dbname: str,
    user: str,
    password: str,
    min_count: int,
    levels: tuple[int, ...],
) -> tuple[Optional[list[dict]], Optional[str]]:
    """psql 子进程拉取模板。成功返回 (rows, None)；失败返回 (None, 固定错误码)。

    输出行格式：normalized|level|count|stability|raw
    （heading_raw 放最后：原始标题可能含 |，split 限次保尾部完整）
    """
    levels_sql = ",".join(str(lv) for lv in levels)
    sql = (
        f"SELECT heading_normalized, heading_level, count, stability_score, heading_raw "
        f"FROM {LIBRARY_TABLE} "
        f"WHERE heading_level IN ({levels_sql}) AND count >= {int(min_count)} "
        f"ORDER BY count DESC"
    )
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    cmd = [
        "psql",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", dbname,
        "--no-psqlrc",
        "--tuples-only",
        "--field-separator=|",
        "-v", "ON_ERROR_STOP=1",
        "-c", sql,
    ]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return None, "H2_LIB_NO_PSQL"
    except subprocess.TimeoutExpired:
        return None, "H2_LIB_TIMEOUT"
    except Exception:
        return None, "H2_LIB_PG_FAIL"

    if result.returncode != 0:
        return None, "H2_LIB_PG_FAIL"

    rows: list[dict] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        norm, level_s, count_s, stab_s, raw = (p.strip() for p in parts)
        if not norm or not count_s.isdigit():
            continue
        try:
            level = int(level_s)
            count = int(count_s)
            stability = float(stab_s) if stab_s else None
        except ValueError:
            continue
        rows.append({
            "heading_normalized": norm,
            "heading_level": level,
            "count": count,
            "stability_score": stability,
            "heading_raw": raw,
        })
    if not rows:
        return None, "H2_LIB_EMPTY"
    return rows, None
