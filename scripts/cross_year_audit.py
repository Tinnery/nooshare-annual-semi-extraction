"""
P4 跨年审计：检查同一发行人相邻年份的结构一致性
输出：data/cross_year_audit.jsonl
"""
import json
from pathlib import Path
from collections import defaultdict, Counter


def compute_stability(stock_code: str, reports: list) -> dict:
    """计算单个发行人的跨年稳定性"""
    # 按年份分组
    by_year = defaultdict(list)
    for r in reports:
        by_year[r["report_year"]].append(r)
    
    years = sorted(by_year.keys())
    if len(years) < 2:
        return {
            "stock_code": stock_code,
            "n_years": len(years),
            "stability": None,
            "diffs": [],
            "status": "insufficient_data",
        }
    
    # 检查相邻年份的一致性
    diffs = []
    stable_count = 0
    total_pairs = 0
    
    for i in range(len(years) - 1):
        y1, y2 = years[i], years[i + 1]
        
        # 比较同年同类型报告（年报 vs 年报，半年报 vs 半年报）
        for period in [2, 4]:  # 2=半年报, 4=年报
            r1_list = [r for r in by_year[y1] if r["period"] == period]
            r2_list = [r for r in by_year[y2] if r["period"] == period]
            
            if not r1_list or not r2_list:
                continue
            
            # 取第一份
            r1, r2 = r1_list[0], r2_list[0]
            total_pairs += 1
            
            # 比较核心节
            core_8 = {"company_profile", "mda", "governance", "esg", "matters", "shares", "financial"}
            cats1 = set(h["canonical_cat"] for h in r1["headings"] if h.get("canonical_cat"))
            cats2 = set(h["canonical_cat"] for h in r2["headings"] if h.get("canonical_cat"))
            
            core1 = cats1 & core_8
            core2 = cats2 & core_8
            
            if core1 == core2:
                stable_count += 1
            else:
                diffs.append({
                    "year1": y1,
                    "year2": y2,
                    "period": period,
                    "missing": sorted(core1 - core2),
                    "extra": sorted(core2 - core1),
                    "explainable": False,  # 需要人工判断
                })
    
    stability = stable_count / total_pairs if total_pairs > 0 else None
    
    return {
        "stock_code": stock_code,
        "n_years": len(years),
        "n_pairs": total_pairs,
        "stable_count": stable_count,
        "stability": stability,
        "diffs": diffs,
        "status": "stable" if stability == 1.0 else ("unstable" if stability and stability < 1.0 else "unknown"),
    }


def main():
    # 按 stock_code 分组
    by_stock = defaultdict(list)
    with open("data/h1_full_normalized.jsonl") as f:
        for line in f:
            r = json.loads(line)
            by_stock[r["stock_code"]].append(r)
    
    print(f"总发行人: {len(by_stock)}")
    
    # 审计
    audits = []
    status_dist = Counter()
    stability_values = []
    
    for stock_code, reports in by_stock.items():
        audit = compute_stability(stock_code, reports)
        audits.append(audit)
        status_dist[audit["status"]] += 1
        
        if audit["stability"] is not None:
            stability_values.append(audit["stability"])
    
    # 统计
    print(f"\n状态分布:")
    for s, cnt in status_dist.most_common():
        print(f"  {s}: {cnt}")
    
    if stability_values:
        avg_stability = sum(stability_values) / len(stability_values)
        perfect_stability = sum(1 for s in stability_values if s == 1.0) / len(stability_values)
        print(f"\n平均稳定性: {avg_stability:.3f}")
        print(f"完全稳定率: {perfect_stability:.1%}")
    
    # 保存
    with open("data/cross_year_audit.jsonl", "w") as f:
        for audit in audits:
            f.write(json.dumps(audit, ensure_ascii=False) + "\n")
    
    print(f"\n审计结果已保存: data/cross_year_audit.jsonl")


if __name__ == "__main__":
    main()
