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
from functools import lru_cache
from pathlib import Path

# 章节类别映射函数占位：外部 report_patterns.json 不随包发布，
# None 时类别判定走 _LOCAL_VARIANTS 本地扩展变体表。
_map_heading_to_category = None

from .corpus import cn_to_int, slot_key_from_path
from .numbering import expected_sections
from .morphology import LEGAL_NAMES, RE_LEGAL, _strip_noise
from .pattern_matcher import get_pattern_matcher

# 能力契约标记：供下游校验抽取器是否具备对应能力，防止旧版
# 部署导致 library_match 缺失、命中标准库的 pattern 被误计入统计。
HAS_LIBRARY_MATCH = True
HAS_TITLE_ANCHOR = True
HAS_ORDINAL_VERDICT = True
_TITLE_ANCHOR_ENABLED = os.environ.get("H1_TITLE_ANCHOR", "1") != "0"
# 库词表参与候选代表打分：命中标准库/法规标题的候选优先，修掉正文表格行
# 抢走目录页序号导致的跨层级误识别。设 0 可回到旧的 len(name) 决胜。
HAS_LIBRARY_RANK = True
_LIBRARY_RANK_ENABLED = os.environ.get("H1_LIBRARY_RANK", "1") != "0"

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

# 加载法定章节模板（包内 spec/specs 目录）
_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec" / "specs"
_LC = json.loads((_SPEC_DIR / "legal_chapters.json").read_text(encoding="utf-8"))
TEMPLATE = {k: v["sections"] for k, v in _LC["chapters"].items()}


def reg_version_key(year: int, period: int) -> str | None:
    """返回适用的法规版本 key。
    
    法规版本生效日期：
    - 2016 修订：〔2016〕31号（年报）/ 未单独列出半年报，假设同期适用
    - 2021 修订：〔2021〕15号（年报）/ 〔2021〕16号（半年报）
    - 2025 修订：〔2025〕3号（年报）/ 〔2025〕4号（半年报）
    
    2016 年以前的报告无适用法规版本，返回 None。
    """
    if year < 2016:
        return None  # 无适用法规版本
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


def ordinal_verdict(headings: list[dict]) -> dict:
    """编号序列形态校验：不跳号、不重复。

    纯数字规则，不含任何业务豁免（法规条件章节也一视同仁）：
    - 取 ordinal > 0 的编号标题，按升序应恰好构成 1,2,3,…,N 连续序列；
      「首项必须为 1」已由「不跳号」蕴含（从 2 开始即缺 1）。
    - 重复：同一 ordinal 出现多次。
    - 缺任何序号一律判 GAP，不区分缺的是哪一个。
    ordinal = 0 的无编号一级标题（如「重要提示」「备查文件目录」）不参与序列。

    返回 PASS / GAP / DUPLICATE / NO_NUMBERED，并附缺失与重复的序号。
    """
    ords = [h["ordinal"] for h in headings if (h.get("ordinal") or 0) > 0]
    n = len(ords)
    if n == 0:
        return {"ordinal_valid": False, "ordinal_verdict": "NO_NUMBERED",
                "ordinal_n": 0, "ordinal_missing": [], "ordinal_duplicates": []}

    counts: Counter = Counter(ords)
    dupes = sorted(o for o, c in counts.items() if c > 1)
    uniq = set(ords)
    # 连续 = 1..max 全部出现；max 用实际最大序号（不是 n），
    # 这样 [1..10,13] 会正确报缺 [11,12]
    missing = sorted(set(range(1, max(ords) + 1)) - uniq)

    if dupes:
        verdict = "DUPLICATE"
    elif missing:
        verdict = "GAP"
    else:
        verdict = "PASS"
    return {
        "ordinal_valid": verdict == "PASS",
        "ordinal_verdict": verdict,
        "ordinal_n": n,
        "ordinal_missing": missing,
        "ordinal_duplicates": dupes,
    }


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


@lru_cache(maxsize=16384)
def _in_title_vocab(name: str) -> int:
    """候选标题是否落在标准库/法规有限集里。

    两种情况算命中：本身是标准标题，或去噪/截断后能锚定到标准标题
    （如「重要提示、目录和释义公司董事会…」）。
    """
    m = get_pattern_matcher()
    if m.is_standard_title(name):
        return 1
    return 1 if m.anchor_title(name) else 0


def _rep_rank(it: dict) -> tuple:
    if _LIBRARY_RANK_ENABLED:
        # 命中标准库标题的候选绝对优先；同优先级内不再用 len(name) 决胜，
        # 由候选在原文中的先后顺序决定（先出现的目录页标题胜出）。
        # 这样「一、有限售条件股份」这类正文表格行不会抢走 ord=1/2。
        # 候选集一个都不删，因此不会产生序号空洞。
        return (_in_title_vocab(it["name"]),
                1 if it["md_level"] == 1 else 0,
                1 if it["heading_like"] else 0)
    return (1 if it["md_level"] == 1 else 0,
            1 if it["heading_like"] else 0,
            len(it["name"]))


def _conditional_ords(year: int, period: int) -> set[int]:
    key = reg_version_key(year, period)
    if key is None:
        return set()  # 无适用法规，无条件章节
    return {i for i, sec in enumerate(TEMPLATE[key], start=1) if sec["required"] != "always"}


ORD_CAP = 15


def _detect_l1(items: list[dict], conditional: set[int]) -> list[dict] | None:
    """检测一级标题集合。
    
    C1 修复：解耦原始标题提取与法规规范映射。
    - 不再要求标题必须匹配法规词表（移除 rate < 0.3 阈值）
    - 只要存在足够数量的编号标题（>=4），且形态像标题，就保留
    - 法规匹配在后续 _coverage 阶段单独处理，不丢弃原始证据
    """
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
    # C1: 移除法规匹配率阈值，不再因法规词表不匹配而丢弃原始标题
    # rate = sum(1 for o in ords if legal_name_of(best[o]["name"])) / n
    # if rate < 0.3:
    #     return None
    # 库词表命中本身就是「像标题」的强证据：新 rank 可能选到带点线噪声、
    # heading_like=0 但可锚定到标准标题的候选（如「公司基本情况------」），
    # 若不放宽会把整份报告判成无 headings。仅在 rank 开启时放宽，保证 A/B 干净。
    rank_on = _LIBRARY_RANK_ENABLED
    if not all(best[o]["md_level"] == 1 or best[o]["heading_like"]
               or (rank_on and _in_title_vocab(best[o]["name"])) for o in ords):
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
    """计算法规覆盖率；无法可靠映射类别时明确返回 unavailable，而非伪造 0%。"""
    key = reg_version_key(year, period)
    if key is None:
        return {
            "reg_version": None,
            "spec_applicable": False,
            "coverage_available": False,
            "coverage_status": "NOT_APPLICABLE",
            "expected_sections": None,
            "n_present": None,
            "missing_always_sections": None,
            "missing_conditional_sections": None,
            "is_complete_l1": None,
            "coverage_ratio": None,
        }

    sections = TEMPLATE[key]
    # 类别映射器目前是外部扩展点；未配置时，局部变体表并不能覆盖全部
    # 法规章节。此时不能将空 category 集合解释成所有法定章节均缺失。
    if _map_heading_to_category is None:
        return {
            "reg_version": key,
            "spec_applicable": True,
            "coverage_available": False,
            "coverage_status": "CATEGORY_MAPPING_UNAVAILABLE",
            "expected_sections": len(sections),
            "n_present": None,
            "missing_always_sections": None,
            "missing_conditional_sections": None,
            "is_complete_l1": None,
            "coverage_ratio": None,
        }

    present_cats = {h["canonical_cat"] for h in headings if h.get("canonical_cat")}
    missing_always, missing_conditional = [], []
    for i, sec in enumerate(sections, start=1):
        cat = _map_heading_to_category(sec["name"]) or ""
        req = sec["required"]
        if cat not in present_cats:
            (missing_conditional if req != "always" else missing_always).append(i)
    always_total = sum(1 for sec in sections if sec["required"] == "always")
    cov = (always_total - len(missing_always)) / always_total if always_total else 1.0
    return {
        "reg_version": key,
        "spec_applicable": True,
        "coverage_available": True,
        "coverage_status": "ASSESSED",
        "expected_sections": len(sections),
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
    s_chzh = _detect_l1(chzh, cond)
    s_cn = _detect_l1(cn, cond) if not s_chzh else None
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
        b = _detect_l1(body_chzh, cond)
        t = _detect_l1(toc_chzh, cond)
        if b and t:
            a = {it["ordinal"] for it in b}
            bb = {it["ordinal"] for it in t}
            if a or bb:
                dual = round(len(a & bb) / len(a | bb), 4)
    else:
        toc_recovered = _recover_from_toc(toc_lines)
        # C1: expected 可能为 None（无适用法规），此时用默认阈值 4
        toc_threshold = max(2, (expected or 6) - 2)
        if len(toc_recovered) >= toc_threshold:
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

    cov = _coverage(headings, year, period)

    ov = ordinal_verdict(headings)
    rec = {
        "slot_key": slot, "stock_code": code, "report_year": year, "period": period,
        "source_sha256": sha, "n_bytes": len(raw),
        "extraction_method": method,
        "n_headings": len(headings),
        "ordinal_valid": ov["ordinal_valid"],
        "ordinal_verdict": ov["ordinal_verdict"],
        "ordinal_n": ov["ordinal_n"],
        "ordinal_missing": ov["ordinal_missing"],
        "ordinal_duplicates": ov["ordinal_duplicates"],
        "is_complete_l1": cov["is_complete_l1"],
        "coverage_ratio": cov["coverage_ratio"],
        "missing_always_sections": cov["missing_always_sections"],
        "missing_conditional_sections": cov["missing_conditional_sections"],
        "reg_version": cov["reg_version"],
        "spec_applicable": cov["spec_applicable"],
        "coverage_available": cov["coverage_available"],
        "coverage_status": cov["coverage_status"],
        "expected_sections": cov["expected_sections"],
        "n_candidate_sets": 1 if primary_set else 0,
        "dual_agreement": dual,
        "library_match": library_match is not None,
        "library_count": library_match["count"] if library_match else None,
        "headings": headings,
    }

    return rec


def extract_batch(
    root: Path,
    out: Path,
    failures: Path,
    limit: int = 0,
    offset: int = 0,
    append: bool = False,
) -> dict:
    """批量抽取 H1 标题；将法规不适用、覆盖率不可评估和结构残差分开统计。"""
    files = sorted(root.rglob("*.md"))
    if offset:
        files = files[offset:]
    if limit:
        files = files[:limit]

    method_counter: Counter = Counter()
    ordinal_counter: Counter = Counter()
    complete = 0
    residual = 0
    n_spec_applicable = 0
    n_spec_not_applicable = 0
    n_coverage_evaluated = 0
    n_coverage_unavailable = 0
    n_without_headings = 0
    n_extraction_errors = 0
    n_skipped = 0
    dual_vals: list[float] = []
    missing_always_freq: Counter = Counter()
    n_headings_total = 0
    n_ok = 0

    mode = "a" if append else "w"
    with (\n        out.open(mode, encoding="utf-8") as fout,\n        failures.open(mode, encoding="utf-8") as ffail,\n    ):
        for i, path in enumerate(files, start=1):
            try:
                rec = extract(path)
            except Exception as exc:
                ffail.write(json.dumps({
                    "path": str(path),
                    "reason": "EXTRACTION_ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                }, ensure_ascii=False) + "\n")
                residual += 1
                n_extraction_errors += 1
                continue

            if rec is None:
                n_skipped += 1
                continue

            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_ok += 1
            method_counter[rec["extraction_method"]] += 1
            n_headings_total += rec["n_headings"]

            # C1 的 None 表示法规不适用，不是“缺少全部法定章节”。
            # 兼容旧记录：spec_applicable 缺失时才根据 reg_version 推断。
            spec_applicable = rec.get("spec_applicable")
            if spec_applicable is None:
                spec_applicable = rec.get("reg_version") is not None

            reasons: list[str] = []
            if spec_applicable:
                n_spec_applicable += 1
                coverage_available = rec.get("coverage_available")
                if coverage_available is None:
                    coverage_available = rec.get("coverage_ratio") is not None
                if coverage_available:
                    n_coverage_evaluated += 1
                    if rec.get("is_complete_l1") is True:
                        complete += 1
                    elif rec.get("is_complete_l1") is False:
                        reasons.append("REGULATORY_COVERAGE_INCOMPLETE")
                    for missing in (rec.get("missing_always_sections") or []):
                        missing_always_freq[missing] += 1
                else:
                    n_coverage_unavailable += 1
            else:
                n_spec_not_applicable += 1

            if rec.get("n_headings", 0) == 0:
                n_without_headings += 1
                reasons.append("NO_HEADINGS")

            ordinal_verdict = rec.get("ordinal_verdict", "UNKNOWN")
            ordinal_counter[ordinal_verdict] += 1
            if ordinal_verdict != "PASS":
                reasons.append(f"ORDINAL_{ordinal_verdict}")

            if reasons:
                residual += 1
                ffail.write(json.dumps({
                    "slot_key": rec["slot_key"],
                    "reasons": reasons,
                    "method": rec["extraction_method"],
                    "spec_applicable": spec_applicable,
                    "coverage_status": rec.get("coverage_status"),
                    "missing_always": rec.get("missing_always_sections"),
                    "ordinal_verdict": ordinal_verdict,
                }, ensure_ascii=False) + "\n")

            if rec.get("dual_agreement") is not None:
                dual_vals.append(rec["dual_agreement"])
            if i % 3000 == 0:
                print(
                    f"  {i}/{len(files)} ok={n_ok} complete={complete} "
                    f"residual={residual} not_applicable={n_spec_not_applicable}",
                    flush=True,
                )

    return {
        "n_files": len(files),
        "n_ok": n_ok,
        "n_skipped": n_skipped,
        "n_extraction_errors": n_extraction_errors,
        "n_spec_applicable": n_spec_applicable,
        "n_spec_not_applicable": n_spec_not_applicable,
        "n_coverage_evaluated": n_coverage_evaluated,
        "n_coverage_unavailable": n_coverage_unavailable,
        "n_without_headings": n_without_headings,
        "complete": complete,
        "residual": residual,
        "method_distribution": method_counter.most_common(),
        "ordinal_verdict_distribution": ordinal_counter.most_common(),
        "avg_headings": n_headings_total / max(1, n_ok),
        "missing_always_freq": missing_always_freq.most_common(),
        "dual_agreement": {
            "count": len(dual_vals),
            "agree_rate": sum(1 for value in dual_vals if value >= 0.98) / len(dual_vals) if dual_vals else 0,
            "mean": sum(dual_vals) / len(dual_vals) if dual_vals else 0,
        },
    }
