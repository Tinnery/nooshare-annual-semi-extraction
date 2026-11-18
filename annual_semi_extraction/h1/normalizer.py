"""H1 规范化后处理。

规则版本：v1.0
- R101: 去除空 canonical_cat
- R102: 去重 canonical_cat（保留首次）
- R103: 噪声标记（空/片段/过长）
- R104: 模板基座校验（核心 7 类）
"""

from collections import Counter


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
        "description": "检查核心 7 类是否齐全，标记 template_compliance"
    },
}


def normalize_report(report: dict) -> dict:
    """对单份报告做规范化。"""
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
            deduped.append(h)
    if len(deduped) < len(headings):
        applied_rules.append("R102")
    headings = deduped
    
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
        core_categories = {"company_profile", "mda", "governance", "esg", "matters", "shares", "financial"}
        cat_set = set(cats)
        if core_categories.issubset(cat_set):
            result["normalization_status"] = "valid"
            result["template_compliance"] = "full"
            applied_rules.append("R104")
        else:
            result["normalization_status"] = "incomplete"
            result["template_compliance"] = "partial"
            missing = core_categories - cat_set
            result["missing_core"] = sorted(missing)
            applied_rules.append("R104")
    
    result["applied_rules"] = applied_rules
    result["normalization_version"] = "v1.0"
    
    return result
