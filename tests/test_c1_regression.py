"""C1 修复回归测试：验证历史报告（2003-2012）的 H1 抽取。

问题 A 修复：H1 抽取与法规匹配解耦
- 不再因法规词表不匹配而丢弃原始标题
- 注册表未覆盖的历史期间标记为法规版本未解析
- coverage_ratio 不再伪装成 0.0
"""
import json
import tempfile
from pathlib import Path

import pytest

from annual_semi_extraction.h1.extractor import (
    extract,
    reg_version_key,
    _detect_l1,
    _coverage,
    extract_batch,
)
from annual_semi_extraction.h1.numbering import expected_sections


class TestRegVersionKey:
    """法规版本映射测试。"""
    
    def test_pre_2016_returns_none(self):
        """注册表未覆盖的历史期间不伪造法规版本。"""
        assert reg_version_key(2003, 2) is None
        assert reg_version_key(2010, 2) is None
        assert reg_version_key(2015, 2) is None
    
    def test_annual_rules_follow_period_end(self):
        """年度报告按期末日期选用 2016、2021、2025 版本。"""
        assert reg_version_key(2016, 4) == "no2_2016_31"
        assert reg_version_key(2020, 4) == "no2_2016_31"
        assert reg_version_key(2021, 4) == "no2_2021_15"
        assert reg_version_key(2024, 4) == "no2_2021_15"
        assert reg_version_key(2025, 4) == "no2_2025_3"

    def test_semiannual_rules_follow_period_end(self):
        """2025 半年报期末早于 2025-07-01，仍适用 2021 版。"""
        assert reg_version_key(2016, 2) is None  # 注册表尚无该期间版本
        assert reg_version_key(2020, 2) is None  # 注册表尚无该期间版本
        assert reg_version_key(2021, 2) == "no3_2021_16"
        assert reg_version_key(2025, 2) == "no3_2021_16"
        assert reg_version_key(2026, 2) == "no3_2025_4"


class TestExpectedSections:
    """预期章节数测试。"""
    
    def test_pre_2016_returns_none(self):
        """2016 年以前无适用法规，返回 None。"""
        assert expected_sections(2003, 2) is None
        assert expected_sections(2010, 2) is None
    
    def test_missing_registry_period_returns_none(self):
        """注册表未覆盖的期间不得套用默认模板。"""
        assert expected_sections(2016, 2) is None
        assert expected_sections(2020, 2) is None

    def test_annual_expected_sections(self):
        assert expected_sections(2016, 4) == 12
        assert expected_sections(2021, 4) == 10
        assert expected_sections(2025, 4) == 8

    def test_semiannual_expected_sections(self):
        assert expected_sections(2021, 2) == 10
        assert expected_sections(2025, 2) == 10
        assert expected_sections(2026, 2) == 8


class TestDetectL1Decoupled:
    """问题 A 修复：_detect_l1 不再因法规不匹配而丢弃标题。"""
    
    def test_detect_l1_keeps_non_legal_headings(self):
        """即使标题不匹配法规词表，也应保留。"""
        # 模拟 2006 年报告的标题（与 2021 模板不匹配）
        items = [
            {"ordinal": 1, "name": "重要提示", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 1, "start": 0, "end": 10, "verbatim": "第一节 重要提示"},
            {"ordinal": 2, "name": "公司基本情况", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 2, "start": 11, "end": 25, "verbatim": "第二节 公司基本情况"},
            {"ordinal": 3, "name": "主要财务数据和指标", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 3, "start": 26, "end": 45, "verbatim": "第三节 主要财务数据和指标"},
            {"ordinal": 4, "name": "银行业务数据摘要", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 4, "start": 46, "end": 65, "verbatim": "第四节 银行业务数据摘要"},
        ]
        conditional = set()
        result = _detect_l1(items, conditional)
        
        # C1 修复后应保留所有标题，不再因法规不匹配而丢弃
        assert result is not None
        assert len(result) == 4
    
    def test_detect_l1_still_requires_minimum_count(self):
        """少于 4 个标题仍返回 None。"""
        items = [
            {"ordinal": 1, "name": "重要提示", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 1, "start": 0, "end": 10, "verbatim": "第一节 重要提示"},
            {"ordinal": 2, "name": "公司简介", "md_level": 1, "heading_like": True, "system": "CH_ZH", "line": 2, "start": 11, "end": 20, "verbatim": "第二节 公司简介"},
        ]
        conditional = set()
        result = _detect_l1(items, conditional)
        assert result is None


class TestCoverageSpecApplicable:
    """问题 B/C 修复：无适用法规时不伪装成 coverage_ratio=0。"""
    
    def test_coverage_pre_2016_returns_unresolved(self):
        """注册表未覆盖的期间返回 VERSION_UNRESOLVED。"""
        headings = [
            {"canonical_cat": "notice", "raw_name": "重要提示"},
            {"canonical_cat": "company_profile", "raw_name": "公司基本情况"},
        ]
        result = _coverage(headings, year=2006, period=2)
        
        assert result["spec_applicable"] is None
        assert result["spec_resolution_status"] == "UNRESOLVED"
        assert result["reg_version"] is None
        assert result["coverage_ratio"] is None
        assert result["is_complete_l1"] is None
        assert result["missing_always_sections"] is None
    
    def test_coverage_2021_returns_applicable(self):
        """2021 年返回 spec_applicable=True。"""
        headings = [
            {"canonical_cat": "notice", "raw_name": "重要提示、目录和释义"},
            {"canonical_cat": "company_profile", "raw_name": "公司简介和主要财务指标"},
        ]
        result = _coverage(headings, year=2021, period=2)
        
        assert result["spec_applicable"] is True
        assert result["reg_version"] == "no3_2021_16"
        # 当前外部 category mapper 未配置；不能把空映射误判为 0% 覆盖率。
        assert result["coverage_available"] is False
        assert result["coverage_status"] == "CATEGORY_MAPPING_UNAVAILABLE"
        assert result["coverage_ratio"] is None
        assert result["is_complete_l1"] is None


class TestExtractHistoricalReports:
    """端到端测试：历史报告抽取。"""
    
    @pytest.fixture
    def sample_2006_md(self):
        """模拟 2006 年半年报 MD 内容。"""
        return """# 重要提示

公司董事会及董事保证本公告内容不存在任何虚假记载...

# 第二节 公司基本情况

公司名称：平安银行股份有限公司

# 第三节 主要财务数据和指标

本报告期主要财务数据...

# 第四节 银行业务数据摘要

银行业务数据...

# 第五节 股本变动及股东情况

股本变动情况...

# 第六节 董事、监事、高级管理人员情况

董事、监事情况...

# 第七节 公司治理结构

公司治理情况...

# 第八节 股东大会简介

股东大会情况...

# 第九节 财务报告

财务报告内容...

# 第十节 备查文件目录

备查文件...
"""
    
    def test_extract_2006_report_extracts_headings(self, sample_2006_md, tmp_path):
        """2006 年报告应抽取标题，不再返回 extraction_method=none。"""
        # 创建符合 slot_key 格式的文件路径
        report_dir = tmp_path / "000001"
        report_dir.mkdir()
        md_path = report_dir / "000001_2006_2.md"
        md_path.write_text(sample_2006_md, encoding="utf-8")
        
        result = extract(md_path)
        
        assert result is not None
        # C1 修复：应抽取到标题，不再因法规不匹配而丢弃
        assert result["extraction_method"] != "none"
        assert result["n_headings"] >= 4
        
        # 无适用法规
        assert result["spec_applicable"] is None
        assert result["spec_resolution_status"] == "UNRESOLVED"
        assert result["reg_version"] is None
        assert result["coverage_ratio"] is None
        
    @pytest.fixture
    def sample_2021_md(self):
        """模拟 2021 年半年报 MD 内容（符合 2021 模板）。"""
        return """# 第一节 重要提示、目录和释义

重要提示内容...

# 第二节 公司简介和主要财务指标

公司简介...

# 第三节 管理层讨论与分析

管理层讨论...

# 第四节 公司治理

公司治理...

# 第五节 环境和社会责任

环境和社会责任...

# 第六节 重要事项

重要事项...

# 第七节 股份变动及股东情况

股份变动...

# 第八节 优先股相关情况

优先股情况...

# 第九节 债券相关情况

债券情况...

# 第十节 财务报告

财务报告...
"""
    
    def test_extract_2021_report_has_applicable_spec(self, sample_2021_md, tmp_path):
        """2021 年报告应有适用法规。"""
        report_dir = tmp_path / "000001"
        report_dir.mkdir()
        md_path = report_dir / "000001_2021_2.md"
        md_path.write_text(sample_2021_md, encoding="utf-8")
        
        result = extract(md_path)
        
        assert result is not None
        assert result["extraction_method"] != "none"
        
        # 有适用法规
        assert result["spec_applicable"] is True
        assert result["reg_version"] == "no3_2021_16"
        assert result["coverage_available"] is False
        assert result["coverage_status"] == "CATEGORY_MAPPING_UNAVAILABLE"
        assert result["coverage_ratio"] is None



class TestExtractBatchApplicability:
    """批处理必须区分法规不适用与抽取失败。"""

    @staticmethod
    def _write_numbered_report(root: Path, year: int) -> Path:
        report_dir = root / "000001"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"000001_{year}_2.md"
        path.write_text(
            "第一节 历史概况\n正文\n"
            "第二节 公司基本情况\n正文\n"
            "第三节 经营情况\n正文\n"
            "第四节 财务报告\n正文\n",
            encoding="utf-8",
        )
        return path

    def test_pre_2016_none_fields_do_not_crash_batch_or_count_as_failure(self, tmp_path):
        """2016 年前的 coverage None 不应在批处理汇总时被遍历。"""
        root = tmp_path / "published"
        self._write_numbered_report(root, 2006)
        output = tmp_path / "h1.jsonl"
        failures = tmp_path / "failures.jsonl"

        stats = extract_batch(root, output, failures)

        assert stats["n_files"] == 1
        assert stats["n_ok"] == 1
        assert stats["n_spec_not_applicable"] == 0
        assert stats["n_spec_unresolved"] == 1
        assert stats["n_spec_applicable"] == 0
        assert stats["complete"] == 0
        assert stats["residual"] == 0
        assert stats["n_extraction_errors"] == 0
        record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
        assert record["missing_always_sections"] is None
        assert record["spec_applicable"] is None
        assert record["spec_resolution_status"] == "UNRESOLVED"
        assert record["coverage_ratio"] is None
        assert failures.read_text(encoding="utf-8") == ""

    def test_applicable_but_unmapped_coverage_is_not_a_zero_percent_failure(self, tmp_path):
        """规则适用但类别映射器缺失时，H1 原始抽取保留，覆盖率标记不可评估。"""
        root = tmp_path / "published"
        self._write_numbered_report(root, 2021)
        output = tmp_path / "h1.jsonl"
        failures = tmp_path / "failures.jsonl"

        stats = extract_batch(root, output, failures)

        assert stats["n_ok"] == 1
        assert stats["n_spec_applicable"] == 1
        assert stats["n_coverage_unavailable"] == 1
        assert stats["n_coverage_evaluated"] == 0
        assert stats["complete"] == 0
        assert stats["residual"] == 0
        record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
        assert record["spec_applicable"] is True
        assert record["coverage_available"] is False
        assert record["coverage_ratio"] is None
        assert failures.read_text(encoding="utf-8") == ""
