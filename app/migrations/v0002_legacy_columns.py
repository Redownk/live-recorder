"""版本 2：补齐历史配置、备注、本地视频路径和录制日志默认值。"""

from sqlalchemy import text

from app.migrations.v0001_baseline import upgrade as create_schema


async def upgrade(conn):
    """修复旧版本表结构，已有字段和记录保持原值。"""
    settings_columns = await conn.execute(text("PRAGMA table_info(recording_settings)"))
    settings_names = {column[1] for column in settings_columns.all()}
    for name, definition in (
        ("quality", "VARCHAR(16) NOT NULL DEFAULT 'best'"),
        ("segment_minutes", "INTEGER NOT NULL DEFAULT 0"),
        ("disk_protection_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
        ("disk_min_free_gb", "INTEGER NOT NULL DEFAULT 5"),
        ("disk_stop_free_gb", "INTEGER NOT NULL DEFAULT 1"),
        ("health_check_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
        ("health_startup_timeout_seconds", "INTEGER NOT NULL DEFAULT 60"),
        ("health_stall_timeout_seconds", "INTEGER NOT NULL DEFAULT 60"),
        ("health_max_restarts", "INTEGER NOT NULL DEFAULT 3"),
    ):
        if name not in settings_names:
            await conn.execute(text(f"ALTER TABLE recording_settings ADD COLUMN {name} {definition}"))
    room_columns = await conn.execute(text("PRAGMA table_info(live_room)"))
    if "remark" not in {column[1] for column in room_columns.all()}:
        await conn.execute(text("ALTER TABLE live_room ADD COLUMN remark VARCHAR(512)"))
    video_columns = await conn.execute(text("PRAGMA table_info(live_room_log_video)"))
    if "file_path" not in {column[1] for column in video_columns.all()}:
        await conn.execute(text("ALTER TABLE live_room_log_video ADD COLUMN file_path TEXT"))
    await _ensure_sqlite_defaults(conn)
    log_columns = await conn.execute(text("PRAGMA table_info(live_room_log)"))
    log_names = {column[1] for column in log_columns.all()}
    if "interrupted" not in log_names:
        await conn.execute(text("ALTER TABLE live_room_log ADD COLUMN interrupted BOOLEAN NOT NULL DEFAULT 0"))
    if "health_restart_count" not in log_names:
        await conn.execute(text("ALTER TABLE live_room_log ADD COLUMN health_restart_count INTEGER NOT NULL DEFAULT 0"))
    if "health_last_error" not in log_names:
        await conn.execute(text("ALTER TABLE live_room_log ADD COLUMN health_last_error TEXT"))


async def _ensure_sqlite_defaults(conn):
    """为旧日志表补齐默认值，重建时保留日志 ID、录制信息和健康状态。"""
    current_tables = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    table_names = {row[0] for row in current_tables.all()}

    result = await conn.execute(text("PRAGMA table_info(live_room_log)"))
    columns = result.mappings().all()
    create_time = next((column for column in columns if column["name"] == "create_time"), None)
    del_flag = next((column for column in columns if column["name"] == "del_flag"), None)
    has_required_defaults = (
        create_time is not None
        and create_time["dflt_value"]
        and del_flag is not None
        and del_flag["dflt_value"] is not None
    )
    if has_required_defaults:
        return

    if "live_room_log_old" in table_names:
        raise RuntimeError("发现遗留 live_room_log_old 表，请先检查备份及历史数据后再升级")

    for index_name in (
        "ix_live_room_log_live_room_id",
        "ix_live_room_log_platform",
        "ix_live_room_log_del_flag",
    ):
        await conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    await conn.execute(text("ALTER TABLE live_room_log RENAME TO live_room_log_old"))
    await create_schema(conn)
    interrupted_value = "interrupted" if any(column["name"] == "interrupted" for column in columns) else "0"
    health_count = "COALESCE(health_restart_count, 0)" if any(column["name"] == "health_restart_count" for column in columns) else "0"
    health_error = "health_last_error" if any(column["name"] == "health_last_error" for column in columns) else "NULL"
    await conn.execute(text(f"""
        INSERT INTO live_room_log
            (id, live_room_id, platform, owner, start_live, end_live,
             live_time, user_num, total_user, create_time, del_flag, interrupted, health_restart_count, health_last_error)
        SELECT
            id, live_room_id, platform, owner, start_live, end_live,
            live_time, user_num, total_user, COALESCE(create_time, CURRENT_TIMESTAMP), del_flag, {interrupted_value}, {health_count}, {health_error}
        FROM live_room_log_old
    """))
    await conn.execute(text("DROP TABLE live_room_log_old"))
