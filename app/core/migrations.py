"""处理移除直播标题字段的 SQLite 备份与结构迁移。"""

from datetime import datetime
from contextlib import closing
from pathlib import Path
import sqlite3

from sqlalchemy import text


def backup_before_title_removal(database):
    """存在旧标题列时创建一致性备份，首次建库或已迁移时跳过。

    Args:
        database: SQLite 数据库的绝对路径。

    Returns:
        新建备份路径；无需迁移时返回 None。
    """
    database = Path(database)
    if not database.is_file():
        return None
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        legacy = any("title" in {column[1] for column in source.execute(f"PRAGMA table_info({table})")}
                     for table in ("live_room", "live_room_log"))
        if not legacy:
            return None
        directory = database.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f"{database.stem}-before-title-removal-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        try:
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
    return backup


async def remove_title_columns(connection):
    """移除直播间和录制历史标题列，并迁移旧文件名模板。"""
    for table in ("live_room", "live_room_log"):
        result = await connection.execute(text(f"PRAGMA table_info({table})"))
        if "title" in {column[1] for column in result.all()}:
            await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN title"))
    for table in ("recording_settings", "room_recording_settings"):
        await connection.execute(text(f"""
            UPDATE {table} SET filename_template=REPLACE(filename_template, '{{title}}', '{{remark}}')
            WHERE INSTR(filename_template, '{{title}}') > 0
        """))
