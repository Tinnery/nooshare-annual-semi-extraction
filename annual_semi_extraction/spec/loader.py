"""规格文件加载器。

加载 anchors.json、regulatory_versions.json、legal_chapters.json 等规格文件，
供 E1-E6 判定程序使用。
"""

import json
from pathlib import Path
from typing import Any


class SpecLoader:
    """规格文件加载器。"""
    
    def __init__(self, spec_dir: Path | str):
        self.spec_dir = Path(spec_dir)
        if not self.spec_dir.exists():
            raise FileNotFoundError(f"规格目录不存在: {self.spec_dir}")
    
    def _load_json(self, filename: str) -> dict[str, Any]:
        """加载 JSON 文件。"""
        path = self.spec_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"规格文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    
    def load_anchors(self) -> dict[str, Any]:
        """加载锚身份注册表。"""
        return self._load_json("anchors.json")
    
    def load_regulatory_versions(self) -> dict[str, Any]:
        """加载法规版本时间轴。"""
        return self._load_json("regulatory_versions.json")
    
    def load_legal_chapters(self) -> dict[str, Any]:
        """加载法定必披章节清单。"""
        return self._load_json("legal_chapters.json")
    
    def load_chapter_structures(self) -> dict[str, Any]:
        """加载法规章节结构（从 PDF 提取的原始结构）。"""
        return self._load_json("chapter_structures.json")
    
    def get_anchor(self, anchor_id: str) -> dict[str, Any]:
        """获取指定锚的详细信息。"""
        anchors = self.load_anchors()
        for anchor in anchors["anchors"]:
            if anchor["id"] == anchor_id:
                return anchor
        raise ValueError(f"未找到锚: {anchor_id}")
    
    def get_regulatory_version(self, standard: str, document_no: str) -> dict[str, Any]:
        """获取指定法规版本的信息。
        
        Args:
            standard: "第2号" 或 "第3号"
            document_no: 如 "证监会公告〔2025〕3号"
        """
        versions = self.load_regulatory_versions()
        for v in versions["versions"]:
            if v["standard"] == standard and v["document_no"] == document_no:
                return v
        raise ValueError(f"未找到法规版本: {standard} {document_no}")
    
    def get_legal_chapters(self, legal_key: str) -> dict[str, Any]:
        """获取指定法规版本的法定章节清单。
        
        Args:
            legal_key: 法规版本键，如 "no2_2025_3"（对应 regulatory_versions.json 中的 original_file 字段去掉路径和后缀）
        """
        chapters = self.load_legal_chapters()
        if legal_key not in chapters["chapters"]:
            raise ValueError(f"未找到法定章节清单: {legal_key}")
        return chapters["chapters"][legal_key]
