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

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\dev\nooshare-annual-semi")

from heading_corpus import cn_to_int, slot_key_from_path  # noqa: E402
from numbering_combos import expected_sections  # noqa: E402
from heading_morphology import LEGAL_NAMES, RE_LEGAL, _strip_noise  # noqa: E402
from annual_semi.identify._funcs.heading_verify import _map_heading_to_category  # noqa: E402

# 冻结组合库判定（步骤2）：只新增 frozen_verdict 字段，不改动任何既有字段，
# 以保证对旧命中集合的只读回放逐字节零回归。加载失败时降级为 disabled，不影响提取。
try:
    from h1_frozen_judge import get_judge  # noqa: E402
    _JUDGE = get_judge()
    _FROZEN_ENABLED = True
except Exception as _e:  # pragma: no cover - 冻结库缺失时保持旧行为
    _JUDGE = None
    _FROZEN_ENABLED = False
    _FROZEN_LOAD_ERROR = f"{type(_e).__name__}: {_e}"

# 本地扩展变体表：覆盖实报中出现但上游 LEGAL_NAMES / report_patterns.json 未收录的章节名变体。
# 这些变体来自 5k 冒烟残差诊断（000039 A+H、000502 三板等），按类别归并。
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
# 展平为 list（按长度降序，供前缀匹配）
_LOCAL_VARIANT_LIST = sorted(
    (v for vs in _LOCAL_VARIANTS.values() for v in vs),
    key=len, reverse=True
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
RE_TRAIL = re.compile(r"[\.…·\s\d]{2,}$")  # 点线 + 页码尾巴
# 粘连行前缀：报告标题（「2022年年度报告」）与「第一节…」常粘在同一行，剥离后再判编号
TITLE_PREFIX = re.compile(r"^.{0,25}?(?:年度报告|半年度报告)\s*")

_LC = json.loads(
    (Path(__file__).resolve().parents[1] / "annual_semi_extraction/spec/legal_chapters.json")
    .read_text(encoding="utf-8")
)
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
    # 本地扩展变体（优先，因为更具体）
    for ln in _LOCAL_VARIANT_LIST:
        if clean.startswith(ln) or ln.startswith(clean):
            return ln
    # 上游 LEGAL_NAMES
    for ln in LEGAL_NAMES:
        if clean.startswith(ln) or ln.startswith(clean):
            return ln
    # 回退：合法名出现在行首（marker 之后紧接），从脏名里捞回
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
        # 截断紧跟在正文章节名后的正文（如「第一节 重要提示… 公司董事会…」粘连行）
        # 分割符含中文逗号/句号/分号/冒号/空白 + 【】[] 括号（声明/释义粘连）
        name = re.split(r"[\s，。；：】【\[\]]", name, maxsplit=1)[0].strip()
        return {"system": system, "ordinal": ordinal, "name": name,
                "kind": kind, "marker": marker}
    return None


def _heading_like(body: str) -> bool:
    head = RE_TRAIL.sub("", body).strip()
    return len(head) <= 60


def _make_heading(item: dict, verbatim: str) -> dict:
    legal = legal_name_of(item["name"])
    cat = _map_heading_to_category(item["name"]) or ""
    # 回退：上游 _map_heading_to_category 未识别时，查本地变体表
    if not cat:
        for variant_cat, variants in _LOCAL_VARIANTS.items():
            if any(item["name"].startswith(v) or v.startswith(item["name"]) for v in variants):
                cat = variant_cat
                break
    return {
        "ordinal": item["ordinal"],
        "marker": item.get("marker", ""),
        "raw_name": item["name"],
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
    """同一序数多个候选时，优先 H1 层、其次像标题、再次名更长。"""
    return (1 if it["md_level"] == 1 else 0, 1 if it["heading_like"] else 0, len(it["name"]))


def _conditional_ords(year: int, period: int) -> set[int]:
    """该 reg_version 下「满足条件才必披」的节序号（如 2021 版的 8 优先股、9 债券）。"""
    key = reg_version_key(year, period)
    return {i for i, sec in enumerate(TEMPLATE[key], start=1) if sec["required"] != "always"}


ORD_CAP = 15  # 任何年报/半年报顶层章节数上限（含 A+H 变体）；超出视为脚注/正文噪声


def _detect_l1(items: list[dict], expected: int, conditional: set[int]) -> list[dict] | None:
    """抽取一个「合理」的一级章节集合——只做质量门，不做齐全性裁决。

    **抽取与校验分离**（对应「更深」的正确性定义）：
    抽取阶段只判断「这像不像一组顶层章节」，不要求应披节全在、不要求序号连续、
    不卡 reg_version 的应披节清单——这些齐全性裁决全部交给 `_coverage`，
    且 `_coverage` 按**规范类别(canonical_cat)**匹配，对 A+H 重编号、
    2021↔2025 章节名漂移都鲁棒。

    质量门（任一不满足即丢弃，避免把脚注/正文噪声当章节）：
    - 去重后序数须 1..ORD_CAP（干掉「第571章」类脚注误命中）；
    - 章节数 ≥4（任何法定报告至少 8 节，<4 必为噪声）；
    - 法定名命中率 ≥0.3（放宽到 0.3，容纳非A股模板如退市/三板，其章节名不在A股法定集）；
    - H1 层(`#`)一律接受，非 H1 层仅当「像标题」才接受。
    不要求逐行连续：TOC 行与正文行混排、某节名行出现两次，都通过去重消解。
    """
    if not items:
        return None
    best: dict[int, dict] = {}
    for it in items:
        o = it["ordinal"]
        if o < 1 or o > ORD_CAP:        # 噪声过滤（脚注/附录误命中）
            continue
        if o not in best or _rep_rank(it) > _rep_rank(best[o]):
            best[o] = it
    ords = sorted(best)
    n = len(ords)
    if n < 4:
        return None
    rate = sum(1 for o in ords if legal_name_of(best[o]["name"])) / n
    if rate < 0.3:  # 放宽到 0.3，容纳非A股模板
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
    """按**规范类别**与法规模板比对（不按位置序号）——对 A+H 重编号鲁棒。

    每个模板章节用 `_map_heading_to_category(章节名)` 得到规范类别；
    与每个抽取标题的 `canonical_cat` 比对。两类匹配即通过，因此
    「财务报告被排到第 9 节」「公司治理与环境社会合并为一节」等重编号/
    合并都不会被误判为缺失。条件节(优先股/债券)依法可省略，不算失败。
    """
    key = reg_version_key(year, period)
    sections = TEMPLATE[key]
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
        "reg_version": key, "expected_sections": len(sections),
        "n_present": len(present_cats),
        "missing_always_sections": missing_always,
        "missing_conditional_sections": missing_conditional,
        "is_complete_l1": len(missing_always) == 0,
        "coverage_ratio": round(cov, 4),
    }


def extract(path: Path) -> dict | None:
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
        # 粘连行：报告标题（如「2022年年度报告」）与「第一节…」粘在同一行，
        # 剥离标题前缀后再判编号，避免漏掉第一节。
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
        # 未编号的一级标题（如 `# 重要提示`）：markdown H1 但无「第X节」编号，
        # 能映射到规范类别即记为候选，用于填补编号集合的类别缺口。
        if md_level == 1 and raw_title and not was_numbered:
            cat = _map_heading_to_category(raw_title)
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

    # 主检测：body(`#` 行) 与纯文本行合并为单一池；章节可跨两种形态混排，
    # 同一序数取最优代表（_rep_rank 优先 H1 层）。CN_DUN 作兜底（少数报告用 一、二、三）。
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
        # 补入未编号 H1：仅填补编号集合未覆盖的规范类别（如未编号的「重要提示」）
        present_cats = {h["canonical_cat"] for h in headings}
        for u in h1_unnumbered:
            uh = _make_heading(u, u["verbatim_line"])
            if uh["canonical_cat"] and uh["canonical_cat"] not in present_cats:
                headings.append(uh)
                present_cats.add(uh["canonical_cat"])
        # 双通道一致率：body(`#`) 与 toc(纯文本) 两套 CH_ZH 都有效时比较序数集合
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
        "headings": headings,
    }

    # 冻结库判定：仅追加字段。H1_FROZEN_EMIT=0 时完全不输出该键，
    # 用于步骤4 的「只读回放逐字节零回归」对比。
    if os.environ.get("H1_FROZEN_EMIT", "1") != "0":
        if _JUDGE is not None:
            try:
                rec["frozen_verdict"] = _JUDGE.judge(headings)
            except Exception as e:
                rec["frozen_verdict"] = {"verdict": "judge_error",
                                         "error": f"{type(e).__name__}: {e}"}
        else:
            rec["frozen_verdict"] = {"verdict": "disabled",
                                     "error": globals().get("_FROZEN_LOAD_ERROR", "")}
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/md_cache/published")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--out", default="data/h1_full.jsonl")
    ap.add_argument("--failures", default="data/h1_failures.jsonl")
    ap.add_argument("--append", action="store_true", help="追加模式，不覆盖输出文件")
    ap.add_argument("--no-frozen", action="store_true",
                    help="关闭冻结库判定输出（等价于 H1_FROZEN_EMIT=0，用于零回归回放）")
    args = ap.parse_args()
    if args.no_frozen:
        os.environ["H1_FROZEN_EMIT"] = "0"

    files = sorted(Path(args.root).rglob("*.md"))
    if args.offset:
        files = files[args.offset:]
    if args.limit:
        files = files[: args.limit]

    method_counter: Counter = Counter()
    verdict_counter: Counter = Counter()
    complete = 0
    residual = 0
    dual_vals: list[float] = []
    missing_always_freq: Counter = Counter()
    n_headings_total = 0
    n_ok = 0

    mode = "a" if args.append else "w"
    with Path(args.out).open(mode, encoding="utf-8") as fout, \
         Path(args.failures).open(mode, encoding="utf-8") as ffail:
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

    print(f"\n完成 {n_ok}/{len(files)} 份")
    print(f"方法分布: {method_counter.most_common()}")
    if verdict_counter:
        print(f"冻结库判定分布: {verdict_counter.most_common()}")
    print(f"完整L1(应披节全在): {complete} ({complete/max(1,n_ok):.1%})")
    print(f"残差(不完整/无): {residual} ({residual/max(1,n_ok):.1%})")
    print(f"平均每文件一级标题数: {n_headings_total/max(1,n_ok):.1f}")
    print(f"缺失应披节频率(ordinal->次数): {missing_always_freq.most_common()}")
    if dual_vals:
        agree = sum(1 for d in dual_vals if d >= 0.98)
        print(f"双通道可比 {len(dual_vals)} 份, 一致率>=0.98 占 {agree/len(dual_vals):.1%}, "
              f"均值 {sum(dual_vals)/len(dual_vals):.3f}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
