"""E1 判定程序测试。

测试 E1 判定程序的各个组件和边界情况。
"""

import pytest
from pathlib import Path

from annual_semi_extraction.spec.loader import SpecLoader
from annual_semi_extraction.e1.judge import E1Judge, MissingState, ChapterCompliance


@pytest.fixture
def spec_loader():
    """创建规格加载器（从包内 spec/specs 目录加载）。"""
    return SpecLoader()


@pytest.fixture
def e1_judge(spec_loader):
    """创建 E1 判定程序。"""
    return E1Judge(spec_loader)


@pytest.fixture
def resolved_judge(spec_loader):
    """创建已裁决适用规则的 E1 判定程序。"""
    judge = E1Judge(spec_loader)
    judge._applicability_resolved = True
    return judge


class TestSpecLoader:
    """测试规格加载器。"""
    
    def test_load_regulatory_versions(self, spec_loader):
        """测试加载法规版本时间轴。"""
        versions = spec_loader.load_regulatory_versions()
        assert "versions" in versions
        assert len(versions["versions"]) == 5
        # 检查每个版本都有 chapter_set_key
        for v in versions["versions"]:
            assert "chapter_set_key" in v
    
    def test_load_legal_chapters(self, spec_loader):
        """测试加载法定必披章节清单。"""
        chapters = spec_loader.load_legal_chapters()
        assert "chapters" in chapters
        assert len(chapters["chapters"]) == 5
        assert "no2_2016_31" in chapters["chapters"]
    
    def test_get_regulatory_version(self, spec_loader):
        """测试获取指定法规版本。"""
        version = spec_loader.get_regulatory_version("第2号", "证监会公告〔2025〕3号")
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2025〕3号"
        assert version["effective_from"] == "2025-07-01"
        assert version["chapter_set_key"] == "no2_2025_3"
    
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
        """测试成功初始化。"""
        judge = E1Judge(spec_loader)
        assert judge.spec_loader == spec_loader
        assert judge.legal_chapters is not None
        assert judge.regulatory_versions is not None
    
    def test_init_with_resolved_applicability(self, spec_loader):
        """测试适用规则已裁决状态。"""
        judge = E1Judge(spec_loader)
        judge._applicability_resolved = True
        assert judge._applicability_resolved is True


class TestE1JudgeResolveVersion:
    """测试法规版本解析。"""
    
    def test_resolve_version_resolved(self, resolved_judge):
        """测试已裁决适用规则的版本解析。"""
        version = resolved_judge.resolve_version(4, 2024)
        assert version["standard"] == "第2号"
        assert version["document_no"] == "证监会公告〔2021〕15号"
    
    def test_resolve_version_by_period_end(self, resolved_judge):
        """测试按报告期末确定适用版本。"""
        # 2024 年年报（期末 2024-12-31）适用 〔2021〕15号
        version = resolved_judge.resolve_version(4, 2024)
        assert version["document_no"] == "证监会公告〔2021〕15号"
        
        # 2025 年年报（期末 2025-12-31）适用 〔2025〕3号
        version = resolved_judge.resolve_version(4, 2025)
        assert version["document_no"] == "证监会公告〔2025〕3号"
    
    def test_resolve_version_semi_annual(self, resolved_judge):
        """测试半年报版本解析。"""
        version = resolved_judge.resolve_version(2, 2024)
        assert version["standard"] == "第3号"
        assert version["document_no"] == "证监会公告〔2021〕16号"
    
    def test_resolve_version_invalid_period(self, resolved_judge):
        """测试无效期别。"""
        with pytest.raises(ValueError, match="period 必须是 2 或 4"):
            resolved_judge.resolve_version(3, 2024)


class TestE1JudgeCompliance:
    """测试章节合规判定。"""
    
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
        
        assert result.is_compliant is True
        assert result.compliance_rate == 1.0
        assert len(result.missing) == 0
    
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
        
        assert result.is_compliant is False
        assert len(result.missing) > 0
        assert any("管理层讨论与分析" in m for m in result.missing)
    
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
        
        assert len(result.extra_chapters) > 0
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
        
        assert 0 < result.compliance_rate < 1.0


class TestMissingState:
    """测试缺失状态枚举。"""
    
    def test_missing_state_values(self):
        """测试缺失状态值。"""
        assert MissingState.NOT_DISCLOSED.value == "NOT_DISCLOSED"
        assert MissingState.NOT_APPLICABLE.value == "NOT_APPLICABLE"
        assert MissingState.EXTRACTION_FAILURE.value == "EXTRACTION_FAILURE"
