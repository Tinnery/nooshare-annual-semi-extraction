"""应用配置（从环境变量读取）。"""

import os

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# 语料年份下限：只处理该年及之后的报告（早期报告格式混乱，标准化程度低）。
# 默认 2019，可通过 H1_START_YEAR 环境变量覆盖。
START_YEAR = int(os.environ.get("H1_START_YEAR", "2019"))
