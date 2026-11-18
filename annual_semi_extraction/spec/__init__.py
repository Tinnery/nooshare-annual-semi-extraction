"""规格加载 Unit。

职责：加载法规版本、法定章节清单、锚身份注册表等规格文件。

契约：
- 输入：规格目录路径
- 输出：规格数据结构
- 依赖：无（只读 JSON）
- 副作用：无
"""

from .loader import SpecLoader

__all__ = ["SpecLoader"]
