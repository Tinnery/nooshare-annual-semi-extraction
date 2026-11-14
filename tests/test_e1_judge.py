"""E1 判定程序测试。

测试 E1 判定程序的各个组件和边界情况。
"""

import pytest
from pathlib import Path

from annual_semi_extraction.spec.loader import SpecLoader
from annual_semi_extraction.e1.judge import E1Judge, MissingState, ChapterCompliance


SPEC_DIR = Path(__file__).parents[1] / "annual_semi_extraction" / "spec"


@pytest.fixture
def spec_loader():
    """创建规格加载器。"""
    return SpecLoader(SPEC_DIR)


@pytest.fixture
def e1_judge(spec_loader):
    """创建 E1 判定程序（适用规则已裁决 by_period_end）。"""
    return E1Judge(spec_loader)


class TestSpecLoader:
    """测试规格加载器。"""
    
    def test_load_anchors(self, spec_loader):
        """测试加载锚身份注册表。"""
        anchors = spec_loader.load_anchors()
        assert "anchors" in anchors
        assert len(anchors["anchors"]) == 6
        assert anchors["anchors"][0]["id"] == "E1"
    
    def test_load_regulatory_versions(self, spec_loader):
        """测试加载法规版本时间轴。"""
        versions = spec_loader.load_regulatory_versions()
        assert "versions" in versions
        assert versions["acquisition_status"] == "COMPLETED"
        assert len(versions["versions"]) == 5
    
    def test_load_legal_chapters(self, spec_loader):
        """测试加载法定必披章节清单。"""
        chapters = spec_loader.load_legal_chapters()
        assert "chapters" in chapters
        assert len(chapters["chapters"]) == 5
        assert "no2_2016_31" in chapters["chapters"]
    
    def test_get_anchor(self, spec_loader):
        """测试获取指定锚。"""
        e1 = spec_loader.get_anchor("E1")
        assert e1["id"] == "E1"
        assert "label" in e1
        assert "external_identity" in e1
    
    def test_get_anchor_not_found(self, spec_loader):
        """测试获取不存在的锚。"""
        with pytest.raises(ValueError, match="未找到锚"):
            spec_loader.get_anchor("E99")
    
    def test_get_regulatory_version(self, spec_loader):
        """测试获取指定法规版本。"""
        version = spec_loader.get_regulatory_version("第2号", "证监会公告〔2025〕3号")
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2025〕3号"
        assert version["effective_from"] == "2025-07-01"
    
    def test_get_regulatory_version_not_found(self, spec_loader):
        """测试获取不存在的法规版本。"""
        with pytest.raises(ValueError, match="未找到法规版本"):
            spec_loader.get_regulatory_version("第2号", "证监会公告〔2099〕99号")
    
    def test_get_legal_chapters(self, spec_loader):
        """测试获取法定章节清单。"""
        chapters = spec_loader.get_legal_chapters("no2_2025_3")
        assert "sections" in chapters
        assert len(chapters["sections"]) > 0


class TestE1JudgeInit:
    """测试 E1 判定程序初始化。"""
    
    def test_init_success(self, spec_loader):
        """适用规则已裁决，初始化即可运行判定。"""
        judge = E1Judge(spec_loader)
        assert judge._applicability_resolved is True
    
    def test_init_with_resolved_applicability(self, spec_loader):
        """Human Gate 已裁决 by_period_end，E1 判定程序解除阻断。"""
        judge = E1Judge(spec_loader)
        assert judge._applicability_resolved is True
        assert judge.regulatory_versions["applicability_rule"] == "by_period_end"


class TestE1JudgeResolveVersion:
    """测试版本解析。"""
    
    def test_resolve_version_resolved(self, e1_judge):
        """适用规则已裁决：resolve_version 不再抛错，按报告期末选版本。"""
        version = e1_judge.resolve_version(period=4, report_year=2023)
        assert version["document_no"] == "证监会公告〔2021〕15号"
    
    def test_resolve_version_by_disclosure_date(self, spec_loader):
        """测试按披露日解析版本（备用规则，仍须可运行）。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        judge.regulatory_versions["applicability_rule"] = "by_disclosure_date"
        
        # 2024-03-15 披露的 2023 年报，应适用 2021 版（2025-07-01 前）
        version = judge.resolve_version(period=4, report_year=2023, disclosure_date="2024-03-15")
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2021〕15号"
        
        # 2025-08-01 披露的年报，应适用 2025 版
        version = judge.resolve_version(period=4, report_year=2024, disclosure_date="2025-08-01")
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2025〕3号"
    
    def test_resolve_version_by_period_end(self, spec_loader):
        """测试按报告期末解析版本（当前生效规则）。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        judge.regulatory_versions["applicability_rule"] = "by_period_end"
        
        # 2023 年年报（期末 2023-12-31），应适用 2021 版
        version = judge.resolve_version(period=4, report_year=2023)
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2021〕15号"
        
        # 2025 年年报（期末 2025-12-31），应适用 2025 版
        version = judge.resolve_version(period=4, report_year=2025)
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2025〕3号"
    
    def test_resolve_version_invalid_period(self, spec_loader):
        """测试无效的期间参数。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        judge.regulatory_versions["applicability_rule"] = "by_disclosure_date"
        
        with pytest.raises(ValueError, match="period 必须是 2 或 4"):
            judge.resolve_version(period=3, report_year=2023, disclosure_date="2024-03-15")
    
    def test_resolve_version_semi_annual(self, spec_loader):
        """测试半年报版本解析。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        judge.regulatory_versions["applicability_rule"] = "by_disclosure_date"
        
        # 2024 年半年报，应适用第3号
        version = judge.resolve_version(period=2, report_year=2024, disclosure_date="2024-08-15")
        assert version["standard"] == "第3号"
        assert version["document_no"] == "证监会公告〔2021〕16号"


class TestE1JudgeCompliance:
    """测试合规判定。"""
    
    @pytest.fixture
    def resolved_judge(self, spec_loader):
        """创建按当前生效规则（by_period_end）运行的判定程序。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        judge.regulatory_versions["applicability_rule"] = "by_period_end"
        return judge
    
    def test_judge_compliant_report(self, resolved_judge):
        """测试合规报告的判定。"""
        # 2024 年年报，适用 2021 版第2号
        disclosed_chapters = [
            "第一节 重要提示、目录和释义",
            "第二节 公司简介和主要财务指标",
            "第三节 管理层讨论与分析",
            "第四节 公司治理",
            "第五节 环境和社会责任",
            "第六节 重要事项",
            "第七节 股份变动及股东情况",
            "第十节 财务报告",
        ]
        
        result = resolved_judge.judge(
            report_id="000001_2024_4",
            period=4,
            report_year=2024,
            disclosed_chapters=disclosed_chapters,
        )
        
        assert isinstance(result, ChapterCompliance)
        assert result.report_id == "000001_2024_4"
        assert result.standard == "第2号"
        assert result.version == "证监会公告〔2021〕15号"
        # 条件必披章节（优先股、债券）应为 NOT_APPLICABLE
        assert len(result.not_applicable) >= 2
        # 已披露的章节不应在 missing 中
        for chapter in disclosed_chapters:
            assert chapter not in result.missing
    
    def test_judge_missing_chapter(self, resolved_judge):
        """测试缺失章节的判定。"""
        # 缺少"第三节 管理层讨论与分析"
        disclosed_chapters = [
            "第一节 重要提示、目录和释义",
            "第二节 公司简介和主要财务指标",
            # 缺少第三节
            "第四节 公司治理",
            "第五节 环境和社会责任",
            "第六节 重要事项",
            "第七节 股份变动及股东情况",
            "第十节 财务报告",
        ]
        
        result = resolved_judge.judge(
            report_id="000002_2024_4",
            period=4,
            report_year=2024,
            disclosed_chapters=disclosed_chapters,
        )
        
        assert "第三节 管理层讨论与分析" in result.missing
        assert not result.is_compliant
    
    def test_judge_order_violation(self, resolved_judge):
        """测试顺序违规的判定。"""
        # 顺序错误：第四节在第三节之前
        disclosed_chapters = [
            "第一节 重要提示、目录和释义",
            "第二节 公司简介和主要财务指标",
            "第四节 公司治理",  # 顺序错误
            "第三节 管理层讨论与分析",  # 顺序错误
            "第五节 环境和社会责任",
            "第六节 重要事项",
            "第七节 股份变动及股东情况",
            "第十节 财务报告",
        ]
        
        result = resolved_judge.judge(
            report_id="000003_2024_4",
            period=4,
            report_year=2024,
            disclosed_chapters=disclosed_chapters,
        )
        
        assert len(result.order_violations) > 0
    
    def test_judge_extra_chapter(self, resolved_judge):
        """测试多余章节的判定。"""
        disclosed_chapters = [
            "第一节 重要提示、目录和释义",
            "第二节 公司简介和主要财务指标",
            "第三节 管理层讨论与分析",
            "第四节 公司治理",
            "第五节 环境和社会责任",
            "第六节 重要事项",
            "第七节 股份变动及股东情况",
            "第十节 财务报告",
            "第十一节 不存在的章节",  # 多余章节
        ]
        
        result = resolved_judge.judge(
            report_id="000004_2024_4",
            period=4,
            report_year=2024,
            disclosed_chapters=disclosed_chapters,
        )
        
        assert "第十一节 不存在的章节" in result.extra_chapters
    
    def test_compliance_rate(self, resolved_judge):
        """测试合规率计算。"""
        # 8 个必披章节（不含条件必披），披露 7 个
        disclosed_chapters = [
            "第一节 重要提示、目录和释义",
            "第二节 公司简介和主要财务指标",
            # 缺少第三节
            "第四节 公司治理",
            "第五节 环境和社会责任",
            "第六节 重要事项",
            "第七节 股份变动及股东情况",
            "第十节 财务报告",
        ]
        
        result = resolved_judge.judge(
            report_id="000005_2024_4",
            period=4,
            report_year=2024,
            disclosed_chapters=disclosed_chapters,
        )
        
        # 合规率 = 7/8 = 0.875
        assert result.compliance_rate == 0.875

    def test_report_id_mismatch_rejected(self, resolved_judge):
        """report_id 与 period/report_year 不一致即判 fail，防止串报告（铁律 4）。"""
        pytest.importorskip("annual_semi.completeness")
        with pytest.raises(ValueError, match="不一致"):
            resolved_judge.judge(
                report_id="000001_2023_4",
                period=4,
                report_year=2024,
                disclosed_chapters=["第一节 重要提示、目录和释义"],
            )


class TestMissingState:
    """测试缺失三态枚举。"""
    
    def test_missing_state_values(self):
        """测试缺失三态枚举值。"""
        assert MissingState.NOT_APPLICABLE.value == "NOT_APPLICABLE"
        assert MissingState.NOT_DISCLOSED.value == "NOT_DISCLOSED"
        assert MissingState.EXTRACTION_FAILURE.value == "EXTRACTION_FAILURE"
