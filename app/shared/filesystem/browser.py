import os
from pathlib import Path, PureWindowsPath
from string import ascii_uppercase

from app.core.config import ROOT_DIR
from app.modules.settings.service import resolve_save_path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".ts", ".flv", ".mov", ".avi", ".webm", ".m4v"}

def list_directories(value: str | None, offset: int, limit: int, include_files=False):
    shortcuts = [
        {"name": "项目目录", "path": str(ROOT_DIR)},
        {"name": "用户目录", "path": str(Path.home())},
    ]
    if value is None:
        if os.name == "nt":
            drives = os.listdrives() if hasattr(os, "listdrives") else [f"{letter}:/" for letter in ascii_uppercase]
            entries = [{"name": str(Path(drive)), "path": str(Path(drive))} for drive in drives if Path(drive).is_dir()]
        else:
            entries = [{"name": "/", "path": "/"}]
        path = None
        parent = None
    else:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("目录路径不能为空或包含控制字符")
        if os.name == "nt":
            windows_path = PureWindowsPath(value)
            if windows_path.drive.startswith("\\\\") or (windows_path.drive and not windows_path.root):
                raise ValueError("请选择本机目录，盘符路径必须从根目录开始")
        directory = resolve_save_path(value)
        if not directory.is_dir():
            raise FileNotFoundError("目录不存在或不是文件夹")
        entries = []
        with os.scandir(directory) as children:
            for child in children:
                try:
                    if child.is_dir():
                        entries.append({"name": child.name, "path": str(directory / child.name)})
                    elif include_files and Path(child.name).suffix.lower() in VIDEO_EXTENSIONS and child.is_file():
                        entries.append({"name": child.name, "path": str(directory / child.name), "is_file": True, "size": child.stat().st_size})
                except OSError:
                    continue
        path = str(directory)
        parent = str(directory.parent) if directory.parent != directory else None
    entries.sort(key=lambda item: (item.get("is_file", False), item["name"].casefold(), item["name"]))
    return {
        "path": path,
        "parent": parent,
        "directories": entries[offset:offset + limit],
        "shortcuts": shortcuts,
        "offset": offset,
        "limit": limit,
        "total": len(entries),
        "has_more": offset + limit < len(entries),
    }
