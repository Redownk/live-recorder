from functools import lru_cache
import sys

import yaml

from app.core.paths import ROOT_DIR, RESOURCE_DIR

CONFIG_PATH = ROOT_DIR / "config.yaml"


@lru_cache
def load_config() -> dict:
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
