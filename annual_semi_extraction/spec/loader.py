"""规格文件加载器。

加载 regulatory_versions.json、legal_chapters.json 等规格文件，
供 E1 判定程序使用。

规格文件来源优先级：
1. 显式指定的 spec_dir（测试用）
2. 包内 spec/specs 目录
"""

import json
from pathlib import Path
from typing import Any


class SpecLoader:
    """规格文件加载器。
    
    默认从包内 spec/specs 目录加载规格文件。
    测试时可显式指定 spec_dir。
    """
    
    def __init__(self, spec_dir: Path | str | None = None):
        if spec_dir is not None:
            self.spec_dir = Path(spec_dir)
            if not self.spec_dir.exists():
                raise FileNotFoundError(f"规格目录不存在: {self.spec_dir}")
        else:
            self.spec_dir = Path(__file__).parent / "specs"
    
    def _load_json(self, filename: str) -> dict[str, Any]:
        """加载 JSON 文件。"""
        path = self.spec_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"规格文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    
    def load_regulatory_versions(self) -> dict[str, Any]:
        """加载法规版本时间轴。"""
        return self._load_json("regulatory_versions.json")
    
    def load_legal_chapters(self) -> dict[str, Any]:
        """加载法定必披章节清单。"""
        return self._load_json("legal_chapters.json")
    
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
    
    def get_legal_chapters(self, chapter_set_key: str) -> dict[str, Any]:
        """获取指定法规版本的法定章节清单。
        
        Args:
            chapter_set_key: 法规版本键，如 "no2_2025_3"
        """
        chapters = self.load_legal_chapters()
        if chapter_set_key not in chapters["chapters"]:
            raise ValueError(f"未找到法定章节清单: {chapter_set_key}")
        return chapters["chapters"][chapter_set_key]
