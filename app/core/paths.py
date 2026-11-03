"""统一定位程序资源和持久化数据目录，兼容源码运行与打包环境。"""


import os
from pathlib import Path
import sys


RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
DEFAULT_DATA_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RESOURCE_DIR
ROOT_DIR = Path(os.getenv("LIVE_RECORDER_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser().resolve()
