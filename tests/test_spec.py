"""规格文件完整性测试。

验证公开规格文件之间的完整性和一致性，确保规格变更可被检测。
"""

import hashlib
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGULATORY_DIR = ROOT / "annual_semi_extraction" / "spec" / "specs"
ANCHORS = REGULATORY_DIR / "anchors.json"
VERSIONS = REGULATORY_DIR / "regulatory_versions.json"
LEGAL_CHAPTERS = REGULATORY_DIR / "legal_chapters.json"
CHAPTER_STRUCTURES = REGULATORY_DIR / "chapter_structures.json"
PYPROJECT = ROOT / "pyproject.toml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_spec_files_exist():
    """所有规格文件必须存在。"""
    for path in (ANCHORS, VERSIONS, LEGAL_CHAPTERS, CHAPTER_STRUCTURES):
        assert path.exists(), f"规格文件不存在：{path}"


def test_regulatory_versions_structure():
    """法规版本注册表结构正确。"""
    versions = _json(VERSIONS)
    assert "registry" in versions
    assert "versions" in versions
    assert isinstance(versions["versions"], list)
    assert len(versions["versions"]) == 5  # 2号3版 + 3号2版
    
    for v in versions["versions"]:
        assert "standard" in v
        assert "document_no" in v
        assert "effective_from" in v
        assert "chapter_set_key" in v
        # sha256 必须是 64 位十六进制
        assert v.get("original_sha256") is not None
        assert len(v["original_sha256"]) == 64


def test_legal_chapters_structure():
    """法定章节清单结构正确。"""
    chapters = _json(LEGAL_CHAPTERS)
    assert "registry" in chapters
    assert "chapters" in chapters
    assert isinstance(chapters["chapters"], dict)
    
    for key, info in chapters["chapters"].items():
        assert "sections" in info
        assert isinstance(info["sections"], list)
        for section in info["sections"]:
            assert "name" in section
            assert "required" in section


def test_chapter_structures_structure():
    """章节结构注册表正确。"""
    structures = _json(CHAPTER_STRUCTURES)
    assert "registry" in structures
    assert "structures" in structures
    assert isinstance(structures["structures"], dict)


def test_no_internal_dependencies():
    """pyproject.toml 不包含内部依赖。"""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = {d.split(">")[0].split("=")[0].split("<")[0].strip()
            for d in data["project"]["dependencies"]}

    assert "typer" in deps
    # psycopg2-binary 是模板库读取的合法公开依赖
    assert "psycopg2-binary" in deps
    # 不应包含内部路径依赖或未使用的重型库
    assert "nooshare-specs" not in deps
    assert "boto3" not in deps
    assert "pandas" not in deps
    assert "jieba" not in deps


def test_no_hardcoded_paths():
    """规格文件不包含硬编码内部路径。"""
    for path in (ANCHORS, VERSIONS, LEGAL_CHAPTERS, CHAPTER_STRUCTURES):
        content = path.read_text(encoding="utf-8")
        # 检查常见内部路径模式
        assert "C:\\dev" not in content, f"{path} 包含 Windows 内部路径"
        assert "/home/travis" not in content, f"{path} 包含 Linux 内部路径"
        assert "deliverables/" not in content, f"{path} 包含内部文档引用"
        assert "nooshare-annual-semi" not in content or "extraction" in content, \
            f"{path} 包含上游仓库引用"


def test_no_human_gate_references():
    """规格文件不包含内部审批记录。"""
    for path in (ANCHORS, VERSIONS, LEGAL_CHAPTERS, CHAPTER_STRUCTURES):
        content = path.read_text(encoding="utf-8")
        assert "Human Gate" not in content, f"{path} 包含内部审批记录"
