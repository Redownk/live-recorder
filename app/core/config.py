"""加载并缓存本地 YAML 配置，供服务启动和平台请求读取。"""


from functools import lru_cache
import sys

import yaml

from app.core.paths import ROOT_DIR, RESOURCE_DIR

CONFIG_PATH = ROOT_DIR / "config.yaml"


@lru_cache
def load_config() -> dict:
    """读取并缓存本地配置，打包运行时按需复制内置配置。

    Returns:
        YAML 配置字典；文件不存在或内容为空时返回空字典。
    """
    bundled_config = RESOURCE_DIR / "config.yaml"
    if getattr(sys, "frozen", False) and not CONFIG_PATH.exists() and bundled_config.is_file():
        ROOT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with CONFIG_PATH.open("xb") as target:
                target.write(bundled_config.read_bytes())
        except FileExistsError:
            pass
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


local_config = load_config()
