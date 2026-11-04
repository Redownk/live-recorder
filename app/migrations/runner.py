"""验证迁移历史并按顺序升级 SQLite，结构与版本记录在同一事务内提交。"""

from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import text

from app.core.logger import get_logger
from app.migrations import v0001_baseline, v0002_legacy_columns, v0003_remove_title


logger = get_logger(__name__)
MIGRATIONS = (
    (1, "baseline", v0001_baseline.upgrade),
    (2, "legacy_columns", v0002_legacy_columns.upgrade),
    (3, "remove_title", v0003_remove_title.upgrade),
)


def validate_history(rows):
    """拒绝未知、缺失或名称不匹配的迁移版本，防止旧程序修改新版本数据库。"""
    expected = [(version, name) for version, name, _ in MIGRATIONS]
    if list(rows) != expected[:len(rows)]:
        raise RuntimeError("数据库迁移历史与当前程序不兼容，请使用匹配的程序版本")
    return len(rows)


def backup_before_upgrade(database: Path):
    """现有业务库存在待执行迁移时创建一致性备份，返回路径或 None。

    该检查在创建引擎前执行，避免 SQLite 备份与升级事务相互等待。
    调用方必须先获取应用单实例锁，阻止其他后端同时写入此数据库。
    """
    if not database.is_file():
        return None
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = source.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall() if "schema_migrations" in tables else []
        applied = validate_history(rows)
        if applied == len(MIGRATIONS) or not (tables - {"schema_migrations", "sqlite_sequence"}):
            return None
        directory = database.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f"{database.stem}-before-upgrade-v{MIGRATIONS[-1][0]:04d}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
        try:
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
    logger.info("数据库升级前备份完成：%s", backup)
    return backup


async def upgrade_database(engine):
    """按版本执行待应用迁移，失败时回滚本次所有结构、数据及版本记录。"""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("数据库版本迁移目前仅支持 SQLite")
    async with engine.begin() as connection:
        # sqlite3 的传统事务模式不会为 DDL 自动开启事务，需要显式开始。
        await connection.execute(text("BEGIN IMMEDIATE"))
        await connection.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        rows = (await connection.execute(text("SELECT version, name FROM schema_migrations ORDER BY version"))).all()
        applied = validate_history([tuple(row) for row in rows])
        for version, name, upgrade in MIGRATIONS[applied:]:
            logger.info("执行数据库升级 version=%s name=%s", version, name)
            await upgrade(connection)
            await connection.execute(text("INSERT INTO schema_migrations (version, name) VALUES (:version, :name)"),
                                     {"version": version, "name": name})
