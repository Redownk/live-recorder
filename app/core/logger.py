# app/core/logger.py
import logging
import sys
from app.core.config import local_config


def setup_logging():
    log_cfg = local_config.get("logging", {})
    log_level = local_config.get("logging", {}).get("level", "INFO").upper()

    # 全局配置：决定了日志长什么样，往哪里输
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    # 遍历并屏蔽不需要的日志
    quiet_loggers = log_cfg.get("quiet_loggers", ["httpx", "httpcore"])
    for logger_name in quiet_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# 获取当前模块 logger 的快捷函数
def get_logger(name: str):
    return logging.getLogger(name)
