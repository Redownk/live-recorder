"""初始化容器的持久化配置，并将信号和退出码交给服务进程。"""

import os
from pathlib import Path
import sys


def main():
    """只在配置不存在时写入无 Cookie 的模板，随后执行容器启动命令。"""
    directory = Path(os.environ.get("LIVE_RECORDER_DATA_DIR", "/data"))
    directory.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name("config.yaml").read_bytes()
    try:
        # 排他创建，避免容器重启时覆盖用户已经保存的 Cookie 和其他设置。
        with (directory / "config.yaml").open("xb") as target:
            target.write(template)
    except FileExistsError:
        pass
    if len(sys.argv) < 2:
        raise SystemExit("容器启动命令不能为空")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
