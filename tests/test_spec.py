"""规格不变量测试：把 01 v2 与其注册表变成机器可判定的对象。

这些断言不是业务逻辑测试，而是失控防御——任何绕过变更流程的规格漂移都会在此失败。
"""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "deliverables" / "01-requirement.md"
ANCHORS = ROOT / "annual_semi_extraction" / "spec" / "anchors.json"
VERSIONS = ROOT / "annual_semi_extraction" / "spec" / "regulatory_versions.json"
LEGAL_CHAPTERS = ROOT / "annual_semi_extraction" / "spec" / "legal_chapters.json"
PYPROJECT = ROOT / "pyproject.toml"


def _pin(name: str, req_text: str) -> str:
    # 01 中以纯文本行登记 sha；注册表文件本身不写自身 sha，避免自指。
    match = re.search(rf"^{name} = ([0-9a-f]{{64}})$", req_text, re.MULTILINE)
    assert match, f"{name} 未在 01-requirement.md 登记"
    return match.group(1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_registry_pins_match_actual_files():
    """注册表变更未同步 01 即失败，强制走变更流程。"""
    req_text = REQ.read_text(encoding="utf-8")
    assert _pin("ANCHOR_REGISTRY_SHA256", req_text) == _sha256(ANCHORS)
    assert _pin("REGULATORY_VERSIONS_SHA256", req_text) == _sha256(VERSIONS)
    assert _pin("LEGAL_CHAPTERS_SHA256", req_text) == _sha256(LEGAL_CHAPTERS)


def test_anchors_are_exactly_e1_e6_with_qualified_identity():
    registry = _json(ANCHORS)
    anchors = registry["anchors"]
    assert [a["id"] for a in anchors] == ["E1", "E2", "E3", "E4", "E5", "E6"]
    for anchor in anchors:
        # 裸标签复用正是 02/03 的空绑定根因：身份必须带 @ 前缀。
        assert anchor["qualified_id"].startswith(anchor["id"] + "@")
        for key in ("label", "v1_meaning", "external_identity", "decision_procedure",
                    "pass_condition", "failure_taxonomy", "bound_requirements"):
            assert anchor[key], f"{anchor['id']} 缺 {key}"
    assert len(registry["meta_rules"]) == 3


def test_v1_e_semantics_preserved_verbatim():
    """v2 只深化判定程序，不得替换 E1-E6 原义。"""
    req_text = REQ.read_text(encoding="utf-8")
    for fragment in (
        "章节完备性 = §2 号准则**当年版本**",
        "误差 ≤0.5% 或绝对差 ≤1 元",
        "下期 ROE/营收增长率方向预测 ≥60% 准确率",
        "同 sha 输入 + 同词典版本 + 同分词器 → 同特征矩阵 hash",
        "1,688 unobtainable 的非随机性量化",
        "卡方 p<0.05",
    ):
        assert fragment in req_text, f"E 原义被改写：{fragment}"


def test_authority_converged_to_single_document():
    req_text = REQ.read_text(encoding="utf-8")
    assert "唯一需求权威" in req_text
    assert "禁止再产生新的 Requirement 代际" in req_text
    for name, marker in (
        ("02-framing-deep-requirements.md", "执行参考（非需求权威）"),
        ("03-framing-execution-plan.md", "历史执行草案（非需求权威）"),
        ("04-deep-rewrite-proposal.md", "已合入归档"),
    ):
        assert marker in (ROOT / "deliverables" / name).read_text(encoding="utf-8")
    assert "（v2）" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "非需求权威" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_data_boundary_forbids_retired_ashare_bulletin_assets():
    registry = _json(ANCHORS)
    authorized = " ".join(registry["authorized_sources"])
    forbidden = " ".join(registry["forbidden_sources"])
    assert "annual_semi.reconciled_report" in authorized and "RustFS" in authorized
    # 03 曾把退役资产当作"前提已验证"；这里把裁定固化为不变量。
    for path in ("source/html/sina", "source/html/cfi", ".trash_20261109",
                 "sina_bulletin.db", "/backup"):
        assert path in forbidden, f"越界源未列入禁止清单：{path}"
    req_text = REQ.read_text(encoding="utf-8")
    assert "未授权输入" in req_text
    assert "从 trash 恢复到 RustFS 属于对退役资产的写操作，禁止" in req_text
    assert "不得据此启动任何 Phase" in (
        ROOT / "deliverables" / "03-framing-execution-plan.md"
    ).read_text(encoding="utf-8")


def test_regulatory_timeline_ordered_and_no_fabricated_hash():
    versions = _json(VERSIONS)
    # 适用规则已由 Human Gate 于 2026-11-13 裁决为 by_period_end；
    # 防止有人悄悄改回 UNRESOLVED 或换成另一规则而不走变更流程。
    assert versions["applicability_rule_status"] == "RESOLVED"
    assert versions["applicability_rule"] == "by_period_end"
    # 法规原文已采集并登记 sha256
    assert versions["acquisition_status"] == "COMPLETED"
    by_standard = {}
    for version in versions["versions"]:
        by_standard.setdefault(version["standard"], []).append(version)
        # 法规原文已采集，sha256 必须非空且为 64 位十六进制
        assert version["original_sha256"] is not None
        assert len(version["original_sha256"]) == 64
        assert all(c in "0123456789abcdef" for c in version["original_sha256"])
        # 原文文件必须存在
        original_file = ROOT / "annual_semi_extraction" / "spec" / version["original_file"]
        assert original_file.exists(), f"原文文件不存在：{version['original_file']}"
    assert set(by_standard) == {"第2号", "第3号"}
    for standard, rows in by_standard.items():
        dates = [r["effective_from"] for r in rows]
        assert dates == sorted(dates) and len(set(dates)) == len(dates), f"{standard} 版本时间轴无序"
        assert all(r["applies_to_period"] == (4 if standard == "第2号" else 2) for r in rows)
    assert any("优先股" in (r["structure_change"] or "") for r in by_standard["第2号"])


def test_unresolved_gates_are_explicit():
    req_text = REQ.read_text(encoding="utf-8")
    # 原条款作为历史记录保留；适用规则已裁决，E1 不再阻断
    assert "未裁决前 E1 判定程序不得运行" in req_text
    assert "by_period_end" in req_text
    assert "Human Gate 2026-11-13 追认" in req_text
    # 法规原文已采集并登记 sha256（2026-11-13 解除）
    assert "已解除" in req_text
    assert "5 份 PDF 已从证监会官网下载并登记 sha256" in req_text
    # 第3号 2025 版文号已核实（2026-11-13 解除）
    assert "证监会公告〔2025〕4号" in req_text
    # 源 HTML/trash 仍未授权
    assert "未授权" in req_text
    assert "Human Gate" in req_text


def test_consumer_contract_declares_zero_consumers():
    text = (ROOT / "deliverables" / "05-consumer-contract.md").read_text(encoding="utf-8")
    assert "运行时消费者数量" in text and "**0**" in text
    assert "尚不存在" in text
    assert "可交付 ≠ 已消费" in text


def test_no_new_dependencies_were_added():
    """落地是规格深化，不是扩依赖；03 的 LLM/向量/解析栈不得悄悄进 pyproject。"""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = {d.split(">")[0].split("=")[0].split("<")[0].strip()
            for d in data["project"]["dependencies"]}
    assert deps == {"boto3", "psycopg2-binary", "python-dotenv", "typer", "pandas", "jieba"}
    dev = {d.split(">")[0].split("=")[0].split("<")[0].strip()
           for d in data["dependency-groups"]["dev"]}
    assert dev == {"pytest"}
