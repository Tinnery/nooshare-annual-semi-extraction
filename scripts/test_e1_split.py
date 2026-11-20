"""测试 E1 判定的拆分匹配功能。"""

import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from annual_semi_extraction.spec_loader import SpecLoader
from annual_semi_extraction.e1_judge import E1Judge


def test_split_matching():
    """测试章节拆分匹配。"""
    spec_dir = PROJECT_ROOT / "annual_semi_extraction" / "spec"
    loader = SpecLoader(spec_dir)
    judge = E1Judge(loader)
    
    # 测试用例 1：平安银行（章节被拆分）
    # 法定章节 "第二节 公司简介和主要财务指标" 被拆分成：
    # - "第一章 公司简介"
    # - "第二章 会计数据和财务指标"
    print("测试用例 1: 平安银行（章节拆分）")
    print("-" * 60)
    
    disclosed_chapters_pingan = [
        "第一章 公司简介",
        "第二章 会计数据和财务指标",
        "第三章 管理层讨论与分析",
        "第四章 公司治理",
        "第五章 环境和社会责任",
        "第六章 重要事项",
        "第七章 股份变动及股东情况",
        "第八章 优先股相关情况",
        "第九章 债券相关情况",
        "第十章 财务报告",
    ]
    
    # 注意：测试用例 1 故意缺少"重要提示"章节，以测试缺失检测
    # 预期结果：合规率 87.5%（8/9 个必披章节匹配）
    
    result = judge.judge(
        report_id="000001_2023_4",
        period=4,
        report_year=2023,
        disclosed_chapters=disclosed_chapters_pingan,
    )
    
    print(f"合规: {result.is_compliant}")
    print(f"合规率: {result.compliance_rate:.2%}")
    print(f"缺失章节: {result.missing}")
    print(f"多余章节: {result.extra_chapters}")
    print()
    
    # 测试用例 2：茅台（标准结构）
    print("测试用例 2: 贵州茅台（标准结构）")
    print("-" * 60)
    
    disclosed_chapters_moutai = [
        "第一节 重要提示、目录和释义",
        "第二节 公司简介和主要财务指标",
        "第三节 管理层讨论与分析",
        "第四节 公司治理",
        "第五节 环境和社会责任",
        "第六节 重要事项",
        "第七节 股份变动及股东情况",
        "第八节 优先股相关情况",
        "第九节 债券相关情况",
        "第十节 财务报告",
    ]
    
    result = judge.judge(
        report_id="600519_2023_4",
        period=4,
        report_year=2023,
        disclosed_chapters=disclosed_chapters_moutai,
    )
    
    print(f"合规: {result.is_compliant}")
    print(f"合规率: {result.compliance_rate:.2%}")
    print(f"缺失章节: {result.missing}")
    print(f"多余章节: {result.extra_chapters}")
    print()
    
    # 测试用例 3：标题措辞差异
    print("测试用例 3: 标题措辞差异（'与' vs '和'）")
    print("-" * 60)
    
    disclosed_chapters_variant = [
        "第一节 重要提示、目录和释义",
        "第二节 公司简介及主要财务指标",  # "及" vs "和"
        "第三节 管理层讨论与分析",
        "第四节 公司治理",
        "第五节 环境与社会责任",  # "与" vs "和"
        "第六节 重要事项",
        "第七节 股份变动及股东情况",
        "第八节 优先股相关情况",
        "第九节 债券相关情况",
        "第十节 财务报告",
    ]
    
    result = judge.judge(
        report_id="test_variant_2023_4",
        period=4,
        report_year=2023,
        disclosed_chapters=disclosed_chapters_variant,
    )
    
    print(f"合规: {result.is_compliant}")
    print(f"合规率: {result.compliance_rate:.2%}")
    print(f"缺失章节: {result.missing}")
    print(f"多余章节: {result.extra_chapters}")


if __name__ == "__main__":
    test_split_matching()
