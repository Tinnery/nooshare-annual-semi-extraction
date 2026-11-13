"""
P3 金标验证：双通道互证
通道1：当前提取结果（h1_full_normalized.jsonl）
通道2：独立重新提取（用不同方法）
输出：data/gold_standard_validation.jsonl
"""
import json
import sys
from pathlib import Path
from collections import Counter

# 添加 scripts 目录到 path
sys.path.insert(0, str(Path(__file__).parent))
from h1_extractor import extract


def validate_report(slot_key: str, current_result: dict) -> dict:
    """对单份报告做双通道验证"""
    # 找到原文路径
    stock_code, year, period = slot_key.split("_")
    md_path = Path(f"data/md_cache/published/{stock_code}/{slot_key}.md")
    
    if not md_path.exists():
        return {
            "slot_key": slot_key,
            "validation_status": "file_missing",
            "channel1_cats": [],
            "channel2_cats": [],
            "agreement": False,
        }
    
    # 通道1：当前结果
    ch1_cats = set(h["canonical_cat"] for h in current_result["headings"] if h.get("canonical_cat"))
    
    # 通道2：独立重新提取
    try:
        ch2_result = extract(md_path)  # 传 Path 对象
        ch2_cats = set(h["canonical_cat"] for h in ch2_result["headings"] if h.get("canonical_cat"))
    except Exception as e:
        return {
            "slot_key": slot_key,
            "validation_status": "extraction_error",
            "channel1_cats": sorted(ch1_cats),
            "channel2_cats": [],
            "agreement": False,
            "error": str(e),
        }
    
    # 比较
    # 节存在性：核心 8 节是否一致
    core_8 = {"company_profile", "mda", "governance", "esg", "matters", "shares", "financial"}
    ch1_core = ch1_cats & core_8
    ch2_core = ch2_cats & core_8
    core_agreement = (ch1_core == ch2_core)
    
    # 槽位对齐：章节集合是否一致（忽略顺序）
    set_agreement = (ch1_cats == ch2_cats)
    
    # 总体一致
    agreement = core_agreement and set_agreement
    
    return {
        "slot_key": slot_key,
        "validation_status": "validated",
        "channel1_cats": sorted(ch1_cats),
        "channel2_cats": sorted(ch2_cats),
        "channel1_method": current_result["extraction_method"],
        "channel2_method": ch2_result["extraction_method"],
        "core_agreement": core_agreement,
        "set_agreement": set_agreement,
        "agreement": agreement,
        "missing_in_ch1": sorted(ch2_cats - ch1_cats),
        "extra_in_ch1": sorted(ch1_cats - ch2_cats),
    }


def main():
    # 加载抽样
    with open("data/gold_sample_slots.json") as f:
        sample_slots = json.load(f)
    
    # 加载当前结果
    current_results = {}
    with open("data/h1_full_normalized.jsonl") as f:
        for line in f:
            r = json.loads(line)
            current_results[r["slot_key"]] = r
    
    # 验证
    validations = []
    status_dist = Counter()
    agreement_count = 0
    
    print(f"开始验证 {len(sample_slots)} 份报告...")
    for i, slot_key in enumerate(sample_slots, 1):
        if i % 50 == 0:
            print(f"  进度: {i}/{len(sample_slots)}")
        
        current = current_results.get(slot_key)
        if not current:
            continue
        
        val = validate_report(slot_key, current)
        validations.append(val)
        status_dist[val["validation_status"]] += 1
        
        if val.get("agreement"):
            agreement_count += 1
    
    # 统计
    validated = [v for v in validations if v["validation_status"] == "validated"]
    total_validated = len(validated)
    
    print(f"\n验证完成")
    print(f"总抽样: {len(sample_slots)}")
    print(f"成功验证: {total_validated}")
    print(f"状态分布: {dict(status_dist)}")
    
    if total_validated > 0:
        print(f"\n一致率: {agreement_count}/{total_validated} = {agreement_count/total_validated:.1%}")
        
        # 核心节一致率
        core_agree = sum(1 for v in validated if v.get("core_agreement"))
        print(f"核心节一致率: {core_agree}/{total_validated} = {core_agree/total_validated:.1%}")
        
        # 集合一致率
        set_agree = sum(1 for v in validated if v.get("set_agreement"))
        print(f"集合一致率: {set_agree}/{total_validated} = {set_agree/total_validated:.1%}")
    
    # 保存
    with open("data/gold_standard_validation.jsonl", "w") as f:
        for v in validations:
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
    
    print(f"\n验证结果已保存: data/gold_standard_validation.jsonl")


if __name__ == "__main__":
    main()
