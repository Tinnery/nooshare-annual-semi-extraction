"""应用配置（从环境变量读取）。"""

import os

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
