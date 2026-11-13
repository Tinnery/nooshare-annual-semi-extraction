"""
P1 规范化：对 h1_full.jsonl 做后处理修复
输出：data/h1_full_normalized.jsonl
规则版本：v1.0
"""
import json
from pathlib import Path
from collections import Counter

# 规则表
RULES = {
    "R101": {
        "name": "去除空 canonical_cat",
        "action": "filter_empty_cat",
        "description": "删除 canonical_cat 为空的标题"
    },
    "R102": {
        "name": "去重 canonical_cat",
        "action": "dedup_cat",
        "description": "保留首次出现的 canonical_cat，删除后续重复"
    },
    "R103": {
        "name": "噪声标记",
        "action": "mark_noise",
        "description": "对 noise_* 类型报告标记 normalization_status=noise"
    },
    "R104": {
        "name": "模板基座校验",
        "action": "validate_template",
        "description": "检查核心 8 节是否齐全，标记 template_compliance"
    },
}


def normalize_report(report: dict) -> dict:
    """对单份报告做规范化"""
    result = dict(report)
    headings = list(report["headings"])
    
    applied_rules = []
    
    # R101: 去除空 canonical_cat
    original_n = len(headings)
    headings = [h for h in headings if h.get("canonical_cat")]
    if len(headings) < original_n:
        applied_rules.append("R101")
    
    # R102: 去重 canonical_cat（保留首次）
    seen_cats = set()
    deduped = []
    for h in headings:
        cat = h.get("canonical_cat")
        if cat and cat not in seen_cats:
            seen_cats.add(cat)
            deduped.append(h)
        elif not cat:
            deduped.append(h)  # 保留空的（后续会被 R101 过滤）
    if len(deduped) < len(headings):
        applied_rules.append("R102")
    headings = deduped
    
    # 更新 headings
    result["headings"] = headings
    result["n_headings"] = len(headings)
    
    # R103: 噪声标记
    cats = [h.get("canonical_cat") for h in headings if h.get("canonical_cat")]
    if len(cats) == 0:
        result["normalization_status"] = "noise_empty"
        applied_rules.append("R103")
    elif len(cats) == 1:
        result["normalization_status"] = "noise_fragment"
        applied_rules.append("R103")
    elif len(cats) > 15:
        result["normalization_status"] = "noise_too_long"
        applied_rules.append("R103")
    else:
        # R104: 模板基座校验
        core_8 = {"company_profile", "mda", "governance", "esg", "matters", "shares", "financial"}
        cat_set = set(cats)
        if core_8.issubset(cat_set):
            result["normalization_status"] = "valid"
            result["template_compliance"] = "full"
            applied_rules.append("R104")
        else:
            result["normalization_status"] = "incomplete"
            result["template_compliance"] = "partial"
            missing = core_8 - cat_set
            result["missing_core"] = sorted(missing)
            applied_rules.append("R104")
    
    result["applied_rules"] = applied_rules
    result["normalization_version"] = "v1.0"
    
    return result


def main():
    in_path = Path("data/h1_full.jsonl")
    out_path = Path("data/h1_full_normalized.jsonl")
    
    total = 0
    status_dist = Counter()
    rule_dist = Counter()
    
    with in_path.open(encoding="utf-8") as fin, \
         out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            report = json.loads(line)
            normalized = normalize_report(report)
            fout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            
            total += 1
            status_dist[normalized["normalization_status"]] += 1
            for r in normalized["applied_rules"]:
                rule_dist[r] += 1
    
    print(f"总报告: {total}")
    print(f"规范化版本: v1.0")
    print(f"输出: {out_path}")
    print()
    print("状态分布:")
    for s, cnt in status_dist.most_common():
        print(f"  {s}: {cnt} ({cnt/total:.1%})")
    print()
    print("规则应用次数:")
    for r, cnt in rule_dist.most_common():
        print(f"  {r}: {cnt}")


if __name__ == "__main__":
    main()
