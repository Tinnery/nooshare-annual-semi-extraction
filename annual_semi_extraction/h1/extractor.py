"""全量 H1（一级章节标题）抽取器 —— 监管锚定的确定性方法（v2：扫全行 + 前缀双向匹配）。

关键修正（相对 v1）：
- 扫描**所有行**（不只 `# ` 行）：一级章节无论是 `# 第一节`、纯文本 `第一节`、
  还是 TOC 行 `第一章 公司简介 ... 17`，都纳入候选。
- 合法名匹配改为**前缀双向**：heading 是 legal 的前缀（截断，如「公司简介」）
  或 legal 是 heading 的前缀（扩展，如「公司治理报告暨企业管治报告」→「公司治理」）
  都算命中 → 章/节混用、A+H 拆分、局部改名都能对齐到法规模板。
- 候选层级放宽：md_level==0 但「行像标题」（剥离点线页码后短）即可成候选；
  TOC 单行恢复（一行含 >=2 marker 的整段吞并）保留为兜底。

输出：流式 JSONL（每文件一行）。零新增依赖。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 上游依赖
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")
try:
    from annual_semi.identify._funcs.heading_verify import _map_heading_to_category
except ImportError:
    _map_heading_to_category = None

from .corpus import cn_to_int, slot_key_from_path
from .numbering import expected_sections
from .morphology import LEGAL_NAMES, RE_LEGAL, _strip_noise
from .frozen_judge import get_judge
from .pattern_matcher import get_pattern_matcher

# 版本标记：下游（rustfs-combo）据此 fail-fast，防止部署旧版导致
# library_match 缺失、命中标准库的 pattern 被误计入统计。
HAS_LIBRARY_MATCH = True
# 标题级锚定开关：设为 0 可回到纯贪心行为，用于零回归 A/B 对比与紧急回退。
HAS_TITLE_ANCHOR = True
_TITLE_ANCHOR_ENABLED = os.environ.get("H1_TITLE_ANCHOR", "1") != "0"

# 本地扩展变体表：覆盖实报中出现但上游 LEGAL_NAMES / report_patterns.json 未收录的章节名变体。
_LOCAL_VARIANTS = {
    "esg": ["环保和社会责任", "环境保护和社会责任", "环境、社会与公司治理", "环境、社会和管治"],
    "shares": ["股份变动及主要股东持股情况", "股份变动及持股情况", "普通股股份变动情况"],
    "mda": ["按照境内证券监管规则编制的经营情况讨论与分析",
            "按照香港证券规则编制的管理层讨论与分析",
            "按内地证券监管规则编制的经营情况讨论与分析",
            "按香港证券监管规则编制的管理层讨论与分析"],
    "company_profile": ["公司基本情况", "公司基本信息", "会计数据和财务指标摘要"],
    "governance": ["董事长致辞", "监事会报告", "董事局报告"],
    "financial": ["2021年半年度财务报告（未经审计）", "2022年半年度财务报告（未经审计）",
                  "按中国企业会计准则编制的财务报告", "财务会计报告"],
    "notice": ["重要提示、目录和释义"],
    "documents": ["备查文件目录"],
    "other": ["其他报送数据"],
}
_LOCAL_VARIANT_LIST = sorted(
    (v for vs in _LOCAL_VARIANTS.values() for v in vs),
    key=lambda v: (-len(v), v)  # 同长度字典序，保证确定性
)

RE_H = re.compile(r"^(#{1,6})\s+(.*)$")
RE_MULTILEVEL = re.compile(r"^\d{1,2}\.\d{1,2}")
FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
PATTERNS = [
    ("CH_ZH",    re.compile(r"^第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])\s*[:：\.．]?\s*(\D.*)$")),
    ("CN_DUN",   re.compile(r"^([一二三四五六七八九十]{1,3})\s*[、\.．]\s*(\D.*)$")),
    ("AR_DOT",   re.compile(r"^(\d{1,2})\s*[\.．、]\s*(\D.*)$")),
    ("AR_PAREN", re.compile(r"^[（(]\s*(\d{1,2})\s*[）)]\s*(\D.*)$")),
    ("PAREN_CN", re.compile(r"^[（(]\s*([一二三四五六七八九十]{1,3})\s*[）)]\s*(\D.*)$")),
]
RE_MARKER = re.compile(r"第\s*([一二三四五六七八九十百零〇0-9]+)\s*([章节部分篇])")
RE_TRAIL = re.compile(r"[\.…·\s\d]{2,}$")
TITLE_PREFIX = re.compile(r"^.{0,25}?(?:年度报告|半年度报告)\s*")

# 加载法定章节模板
_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"
_LC = json.loads((_SPEC_DIR / "legal_chapters.json").read_text(encoding="utf-8"))
TEMPLATE = {k: v["sections"] for k, v in _LC["chapters"].items()}


def reg_version_key(year: int, period: int) -> str:
    if year <= 2024:
        return "no2_2021_15" if period == 4 else "no3_2021_16"
    return "no2_2025_3" if period == 4 else "no3_2025_4"


def legal_name_of(name: str) -> str:
    """前缀双向匹配：heading 是 legal 前缀 或 legal 是 heading 前缀，取最长。
    先查本地扩展变体表，再查上游 LEGAL_NAMES。"""
    clean, _ = _strip_noise(name)
    if not clean:
        return ""
    for ln in _LOCAL_VARIANT_LIST:
        if clean.startswith(ln) or ln.startswith(clean):
            return ln
    for ln in LEGAL_NAMES:
        if clean.startswith(ln) or ln.startswith(clean):
            return ln
    m = RE_LEGAL.match(clean)
    if m:
        return m.group(0)
    return ""


def parse_numbered_line(body: str) -> dict | None:
    if RE_MULTILEVEL.match(body):
        return None
    s = body.translate(FULLWIDTH).strip()
    for system, pat in PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        raw_num = m.group(1)
        ordinal = cn_to_int(raw_num)
        if ordinal is None or ordinal < 1 or ordinal > 60:
            return None
        if system == "CH_ZH":
            name, kind, marker = m.group(3).strip(), m.group(2), "第" + m.group(1) + m.group(2)
        else:
            name, kind, marker = m.group(2).strip(), system, m.group(1)
        name = re.split(r"[\s，。；：】【\[\]]", name, maxsplit=1)[0].strip()
        return {"system": system, "ordinal": ordinal, "name": name,
                "kind": kind, "marker": marker}
    return None


def _heading_like(body: str) -> bool:
    head = RE_TRAIL.sub("", body).strip()
    return len(head) <= 60


def _raw_names_similar(raw1: str, raw2: str) -> bool:
    """判断两个 raw_name 是否相似（用于位置对齐时的安全检查）。
    
    相似条件：
    - 一个是另一个的前缀（处理贪心污染）
    - 或 normalize 后相等
    """
    if not raw1 or not raw2:
        return False
    # 前缀匹配（处理贪心吞入正文）
    if raw1.startswith(raw2) or raw2.startswith(raw1):
        return True
    # normalize 后相等
    from .pattern_matcher import _normalize_heading
    return _normalize_heading(raw1) == _normalize_heading(raw2)


def _make_heading(item: dict, verbatim: str) -> dict:
    # ── 标题级锚定：标准库已有该标题，抽出时立即中止贪心 ──────────
    # 贪心把「释义在本报告书中，除非文义另有所指…」「公司业务概要……」
    # 这类正文/点线粘进标题。若标准库里已有干净标题，就在此截断并回写
    # raw_name，使下游 coverage / pattern / library_match 全部基于干净标题。
    # 未命中标准库或库不可用 → anchored=None，保持原有贪心兜底不变。
    name = item["name"]
    matcher = get_pattern_matcher()
    anchored = matcher.anchor_title(name) if _TITLE_ANCHOR_ENABLED else None
    if anchored is not None:
        name = anchored
    # 标准库标题优先：本身命中标准库时直接用它，不走 legal_name_of 的
    # 「前缀双向扩展」（否则「释义」会被扩展成「释义和重大风险提示」）。
    is_standard = matcher.is_standard_title(name)
    legal = name if is_standard else legal_name_of(name)
    cat = (_map_heading_to_category(name) if _map_heading_to_category else None) or ""
    if not cat:
        for variant_cat, variants in _LOCAL_VARIANTS.items():
            if any(name.startswith(v) or v.startswith(name) for v in variants):
                cat = variant_cat
                break
    return {
        "ordinal": item["ordinal"],
        "marker": item.get("marker", ""),
        "raw_name": name,
        # 标准库标题即规范名；统一处理「锚定后变干净」与「原本就干净」，
        # 避免同一标题出现两种 canonical_name。
        "canonical_name": legal,
        "canonical_cat": cat,
        "line": item["line"],
        "byte_start": item["start"],
        "byte_end": item["end"],
        "md_level": item["md_level"],
        "numbering_system": item["system"],
        "verbatim_line": verbatim,
    }


def _rep_rank(it: dict) -> tuple:
    return (1 if it["md_level"] == 1 else 0, 1 if it["heading_like"] else 0, len(it["name"]))


def _conditional_ords(year: int, period: int) -> set[int]:
    key = reg_version_key(year, period)
    return {i for i, sec in enumerate(TEMPLATE[key], start=1) if sec["required"] != "always"}


ORD_CAP = 15


def _detect_l1(items: list[dict], expected: int, conditional: set[int]) -> list[dict] | None:
    if not items:
        return None
    best: dict[int, dict] = {}
    for it in items:
        o = it["ordinal"]
        if o < 1 or o > ORD_CAP:
            continue
        if o not in best or _rep_rank(it) > _rep_rank(best[o]):
            best[o] = it
    ords = sorted(best)
    n = len(ords)
    if n < 4:
        return None
    rate = sum(1 for o in ords if legal_name_of(best[o]["name"])) / n
    if rate < 0.3:
        return None
    if not all(best[o]["md_level"] == 1 or best[o]["heading_like"] for o in ords):
        return None
    return [best[o] for o in ords]


def _recover_from_toc(toc_lines: list[tuple[int, int, str]]) -> list[dict]:
    recovered: list[dict] = []
    for line_no, line_start, body in toc_lines:
        marks = list(RE_MARKER.finditer(body))
        if len(marks) < 2:
            continue
        for i, m in enumerate(marks):
            s, e = m.start(), (marks[i + 1].start() if i + 1 < len(marks) else len(body))
            frag = body[s:e]
            ordinal = cn_to_int(m.group(1))
            kind = m.group(2)
            name = frag[m.end():].strip()
            legal = legal_name_of(name)
            if not legal:
                continue
            recovered.append({
                "ordinal": ordinal, "kind": kind, "name": legal,
                "line": line_no, "start": line_start + s, "end": line_start + e,
                "md_level": 0, "system": "TOC", "verbatim_line": body,
            })
    best: dict[int, dict] = {}
    for r in recovered:
        if r["ordinal"] not in best or len(r["name"]) > len(best[r["ordinal"]]["name"]):
            best[r["ordinal"]] = r
    return list(best.values())


def _coverage(headings: list[dict], year: int, period: int) -> dict:
    key = reg_version_key(year, period)
    sections = TEMPLATE[key]
    present_cats = {h["canonical_cat"] for h in headings if h.get("canonical_cat")}
    missing_always, missing_conditional = [], []
    for i, sec in enumerate(sections, start=1):
        cat = (_map_heading_to_category(sec["name"]) if _map_heading_to_category else None) or ""
        req = sec["required"]
        if cat not in present_cats:
            (missing_conditional if req != "always" else missing_always).append(i)
    always_total = sum(1 for sec in sections if sec["required"] == "always")
    cov = (always_total - len(missing_always)) / always_total if always_total else 1.0
    return {
        "reg_version": key, "expected_sections": len(sections),
        "n_present": len(present_cats),
        "missing_always_sections": missing_always,
        "missing_conditional_sections": missing_conditional,
        "is_complete_l1": len(missing_always) == 0,
        "coverage_ratio": round(cov, 4),
    }


def extract(path: Path) -> dict | None:
    """抽取单份报告的 H1 标题集合。"""
    slot = slot_key_from_path(path)
    if slot is None:
        return None
    code, year_s, period_s = slot.split("_")
    year, period = int(year_s), int(period_s)
    expected = expected_sections(year, period)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()

    items: list[dict] = []
    h1_unnumbered: list[dict] = []
    toc_lines: list[tuple[int, int, str]] = []
    offset = 0
    for lineno, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
        start, end = offset, offset + len(raw_line)
        offset = end
        line = raw_line.decode("utf-8", errors="replace")
        body = line.rstrip("\r\n")
        hm = RE_H.match(body)
        md_level = len(hm.group(1)) if hm else 0
        raw_title = hm.group(2).strip() if hm else body.strip()
        toc_lines.append((lineno, start, body))
        eff_title = TITLE_PREFIX.sub("", raw_title, count=1)
        was_numbered = False
        if eff_title:
            first = eff_title[:1]
            if first in "第一二三四五六七八九十0123456789（(":
                info = parse_numbered_line(eff_title)
                if info is not None:
                    info.update({"line": lineno, "start": start, "end": end,
                                 "verbatim": line, "md_level": md_level,
                                 "heading_like": _heading_like(info["name"])})
                    items.append(info)
                    was_numbered = True
        if md_level == 1 and raw_title and not was_numbered:
            cat = (_map_heading_to_category(raw_title) if _map_heading_to_category else None)
            if cat and _heading_like(raw_title):
                h1_unnumbered.append({
                    "ordinal": 0, "marker": "", "name": raw_title,
                    "line": lineno, "start": start, "end": end,
                    "md_level": 1, "system": "MD_H1",
                    "verbatim_line": line,
                })

    chzh = [it for it in items if it["system"] == "CH_ZH"]
    cn = [it for it in items if it["system"] == "CN_DUN"]
    body_chzh = [it for it in chzh if it["md_level"] == 1]
    toc_chzh = [it for it in chzh if it["md_level"] == 0]

    cond = _conditional_ords(year, period)
    s_chzh = _detect_l1(chzh, expected, cond)
    s_cn = _detect_l1(cn, expected, cond) if not s_chzh else None
    method = "none"
    headings: list[dict] = []
    dual = None
    primary_set = None
    if s_chzh:
        method, primary_set = "ch_zh", s_chzh
    elif s_cn:
        method, primary_set = "cn_dun", s_cn

    if primary_set:
        headings = [_make_heading(it, it["verbatim"]) for it in primary_set]
        present_cats = {h["canonical_cat"] for h in headings}
        for u in h1_unnumbered:
            uh = _make_heading(u, u["verbatim_line"])
            if uh["canonical_cat"] and uh["canonical_cat"] not in present_cats:
                headings.append(uh)
                present_cats.add(uh["canonical_cat"])
        b = _detect_l1(body_chzh, expected, cond)
        t = _detect_l1(toc_chzh, expected, cond)
        if b and t:
            a = {it["ordinal"] for it in b}
            bb = {it["ordinal"] for it in t}
            if a or bb:
                dual = round(len(a & bb) / len(a | bb), 4)
    else:
        toc_recovered = _recover_from_toc(toc_lines)
        if len(toc_recovered) >= max(2, expected - 2):
            method = "toc_recovery"
            headings = [_make_heading(r, r["verbatim_line"]) for r in toc_recovered]
        elif h1_unnumbered:
            method = "md_h1"
            headings = [_make_heading(u, u["verbatim_line"]) for u in h1_unnumbered]

    # ── 标准库匹配：命中则用库的 canonical_name 替换，避免贪心污染 ──
    library_match = None
    if headings:
        raw_pattern = [h["raw_name"] for h in headings]
        matcher = get_pattern_matcher()
        library_match = matcher.match(raw_pattern)
        if library_match:
            # 用库的 canonical_name 替换现有 headings 的 canonical_name
            # 使用位置对齐（第 i 个标题对应第 i 个标题），而不是 ordinal 对齐
            lib_headings = library_match["headings"]
            for i, h in enumerate(headings):
                if i < len(lib_headings):
                    lib_h = lib_headings[i]
                    # 只有当 raw_name 接近时才替换 canonical_name
                    # 避免把 "公司简介" 错误地替换成 "重要提示、目录和释义"
                    if _raw_names_similar(h["raw_name"], lib_h["raw_name"]):
                        if lib_h.get("canonical_name"):
                            h["canonical_name"] = lib_h["canonical_name"]

    cov = (_coverage(headings, year, period) if headings else {
        "reg_version": reg_version_key(year, period),
        "expected_sections": expected, "n_present": 0,
        "missing_always_sections": list(range(1, expected + 1)),
        "missing_conditional_sections": [], "is_complete_l1": False,
        "coverage_ratio": 0.0,
    })

    rec = {
        "slot_key": slot, "stock_code": code, "report_year": year, "period": period,
        "source_sha256": sha, "n_bytes": len(raw),
        "extraction_method": method,
        "n_headings": len(headings),
        "is_complete_l1": cov["is_complete_l1"],
        "coverage_ratio": cov["coverage_ratio"],
        "missing_always_sections": cov["missing_always_sections"],
        "missing_conditional_sections": cov["missing_conditional_sections"],
        "reg_version": cov["reg_version"],
        "expected_sections": cov["expected_sections"],
        "n_candidate_sets": 1 if primary_set else 0,
        "dual_agreement": dual,
        "library_match": library_match is not None,
        "library_count": library_match["count"] if library_match else None,
        "headings": headings,
    }

    # 冻结库判定
    if os.environ.get("H1_FROZEN_EMIT", "1") != "0":
        try:
            judge = get_judge()
            rec["frozen_verdict"] = judge.judge(headings)
        except Exception as e:
            rec["frozen_verdict"] = {"verdict": "disabled", "error": str(e)}

    return rec


def extract_batch(
    root: Path,
    out: Path,
    failures: Path,
    limit: int = 0,
    offset: int = 0,
    append: bool = False,
    no_frozen: bool = False,
) -> dict:
    """批量抽取 H1 标题，输出 JSONL。返回统计摘要。"""
    if no_frozen:
        os.environ["H1_FROZEN_EMIT"] = "0"

    files = sorted(root.rglob("*.md"))
    if offset:
        files = files[offset:]
    if limit:
        files = files[:limit]

    method_counter: Counter = Counter()
    verdict_counter: Counter = Counter()
    complete = 0
    residual = 0
    dual_vals: list[float] = []
    missing_always_freq: Counter = Counter()
    n_headings_total = 0
    n_ok = 0

    mode = "a" if append else "w"
    with out.open(mode, encoding="utf-8") as fout, \
         failures.open(mode, encoding="utf-8") as ffail:
        for i, p in enumerate(files, start=1):
            try:
                rec = extract(p)
            except Exception as e:
                ffail.write(json.dumps({"path": str(p), "error": f"{type(e).__name__}: {e}"},
                                      ensure_ascii=False) + "\n")
                residual += 1
                continue
            if rec is None:
                continue
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_ok += 1
            method_counter[rec["extraction_method"]] += 1
            if "frozen_verdict" in rec:
                verdict_counter[rec["frozen_verdict"]["verdict"]] += 1
            if rec["is_complete_l1"]:
                complete += 1
            else:
                residual += 1
                ffail.write(json.dumps({"slot_key": rec["slot_key"],
                                        "method": rec["extraction_method"],
                                        "missing_always": rec["missing_always_sections"]},
                                       ensure_ascii=False) + "\n")
            n_headings_total += rec["n_headings"]
            for m in rec["missing_always_sections"]:
                missing_always_freq[m] += 1
            if rec["dual_agreement"] is not None:
                dual_vals.append(rec["dual_agreement"])
            if i % 3000 == 0:
                print(f"  {i}/{len(files)} ok={n_ok} complete={complete} residual={residual}", flush=True)

    return {
        "n_files": len(files),
        "n_ok": n_ok,
        "complete": complete,
        "residual": residual,
        "method_distribution": method_counter.most_common(),
        "verdict_distribution": verdict_counter.most_common(),
        "avg_headings": n_headings_total / max(1, n_ok),
        "missing_always_freq": missing_always_freq.most_common(),
        "dual_agreement": {
            "count": len(dual_vals),
            "agree_rate": sum(1 for d in dual_vals if d >= 0.98) / len(dual_vals) if dual_vals else 0,
            "mean": sum(dual_vals) / len(dual_vals) if dual_vals else 0,
        },
    }
