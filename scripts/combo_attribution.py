"""
P0 归因：596 种一级标题组合的生成路径标签
输出：data/combo_attribution.jsonl
"""
import json
from collections import Counter
from pathlib import Path

# 法规模板基座定义
TEMPLATES = {
    "no2_2021_15": {  # 2021-2024 年报
        "always": ["company_profile", "mda", "governance", "esg", "matters", "shares", "financial"],
        "conditional": ["preferred", "bonds"],
        "front": ["notice", "glossary"],
        "back": ["documents"],
    },
    "no3_2021_16": {  # 2021-2024 半年报
        "always": ["company_profile", "mda", "governance", "esg", "matters", "shares", "financial"],
        "conditional": ["preferred", "bonds"],
        "front": ["notice", "glossary"],
        "back": ["documents"],
    },
    "no2_2025_3": {  # 2025+ 年报（8 节）
        "always": ["company_profile", "mda", "governance", "esg", "matters", "shares", "financial"],
        "conditional": [],
        "front": ["notice", "glossary"],
        "back": ["documents"],
    },
    "no3_2025_4": {  # 2025+ 半年报（8 节）
        "always": ["company_profile", "mda", "governance", "esg", "matters", "shares", "financial"],
        "conditional": [],
        "front": ["notice", "glossary"],
        "back": ["documents"],
    },
}

# 所有已知类别
KNOWN_CATS = {
    "notice", "glossary", "company_profile", "mda", "governance", 
    "esg", "matters", "shares", "preferred", "bonds", "financial", "documents"
}


def classify_combo(combo: tuple) -> dict:
    """对单个组合归因"""
    cats_list = list(combo)
    cats = set(c for c in cats_list if c)  # 去空
    n = len(cats)
    
    # 检测数据质量问题
    has_dup = len(cats_list) != len(set(cats_list))
    has_empty = "" in cats_list
    
    quality_issues = []
    if has_dup:
        quality_issues.append("duplicate_cats")
    if has_empty:
        quality_issues.append("empty_cat")
    
    # 1. 噪声分类
    if n == 0:
        return {
            "variant_type": "noise_empty", 
            "template_id": None, 
            "rule_id": "R001", 
            "evidence": "空组合",
            "quality_issues": quality_issues
        }
    
    if len(cats_list) > 15:  # 用原始长度判断超长
        return {
            "variant_type": "noise_too_long", 
            "template_id": None, 
            "rule_id": "R002", 
            "evidence": f"超长 {len(cats_list)} 节",
            "quality_issues": quality_issues
        }
    
    # 2. 检查是否包含核心节
    core_8 = {"company_profile", "mda", "governance", "esg", "matters", "shares", "financial"}
    has_core_8 = core_8.issubset(cats)
    
    if not has_core_8:
        # 单节或碎片
        if n == 1:
            return {
                "variant_type": "noise_fragment", 
                "template_id": None, 
                "rule_id": "R003", 
                "evidence": f"单节 {list(cats)[0]}",
                "quality_issues": quality_issues
            }
        else:
            # 多节但缺核心
            missing = core_8 - cats
            return {
                "variant_type": "incomplete_core",
                "template_id": None,
                "rule_id": "R004",
                "evidence": f"缺核心节: {sorted(missing)}",
                "quality_issues": quality_issues
            }
    
    # 3. 判断模板基座
    has_preferred = "preferred" in cats
    has_bonds = "bonds" in cats
    
    if has_preferred and has_bonds:
        # 10 节核心 → 2021-2024 模板
        template_id = "no2_2021_15"  # 年报/半年报结构相同
    elif not has_preferred and not has_bonds:
        # 8 节核心 → 2025+ 模板
        template_id = "no2_2025_3"
    else:
        # 部分条件节 → 2021-2024 模板（条件节可省略）
        template_id = "no2_2021_15"
    
    # 4. 判断前后置节
    front_cats = cats & {"notice", "glossary"}
    back_cats = cats & {"documents"}
    extra_cats = cats - core_8 - {"preferred", "bonds"} - front_cats - back_cats
    
    variant_parts = []
    if front_cats:
        variant_parts.append(f"front={sorted(front_cats)}")
    if back_cats:
        variant_parts.append(f"back={sorted(back_cats)}")
    if extra_cats:
        variant_parts.append(f"extra={sorted(extra_cats)}")
    
    variant_type = "template_with_variants" if variant_parts else "template_pure"
    
    result = {
        "variant_type": variant_type,
        "template_id": template_id,
        "rule_id": "R010" if variant_type == "template_pure" else "R011",
        "evidence": "; ".join(variant_parts) if variant_parts else "纯模板",
        "quality_issues": quality_issues
    }
    
    return result


def main():
    # 读取全量结果，统计组合
    combo_counter = Counter()
    with open("data/h1_full.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            cats = tuple(h.get("canonical_cat", "") for h in r["headings"])
            combo_counter[cats] += 1
    
    print(f"总组合数: {len(combo_counter)}")
    
    # 归因
    attributions = []
    variant_dist = Counter()
    template_dist = Counter()
    
    for combo, count in combo_counter.items():
        attr = classify_combo(combo)
        attr["combo"] = list(combo)
        attr["count"] = count
        attributions.append(attr)
        
        variant_dist[attr["variant_type"]] += count
        if attr["template_id"]:
            template_dist[attr["template_id"]] += count
    
    # 输出
    out_path = Path("data/combo_attribution.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for attr in attributions:
            f.write(json.dumps(attr, ensure_ascii=False) + "\n")
    
    print(f"归因表已写入: {out_path}")
    print()
    print("变体类型分布:")
    for vt, cnt in variant_dist.most_common():
        print(f"  {vt}: {cnt} ({cnt/sum(variant_dist.values()):.1%})")
    print()
    print("模板基座分布:")
    for t, cnt in template_dist.most_common():
        print(f"  {t}: {cnt} ({cnt/sum(template_dist.values()):.1%})")
    
    # 统计可归因率
    noise_cnt = sum(cnt for vt, cnt in variant_dist.items() if vt.startswith("noise") or vt == "incomplete_core")
    total = sum(variant_dist.values())
    print(f"\n可归因率: {(total - noise_cnt) / total:.1%}")
    print(f"噪声率: {noise_cnt / total:.1%}")


if __name__ == "__main__":
    main()
