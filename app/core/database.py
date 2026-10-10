
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base

engine = None
AsyncSessionLocal = None


async def init_db(app, db_url: str):
    global engine
    global AsyncSessionLocal

    if db_url.startswith("sqlite"):
        db_path = db_url.replace("sqlite+aiosqlite:///", "", 1)
        if db_path.startswith("./"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        echo=False
    )

    AsyncSessionLocal = async_sessionmaker(
        engine,
        expire_on_commit=False
    )

    app.state.engine = engine
    app.state.db = AsyncSessionLocal

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if db_url.startswith("sqlite"):
            room_columns = await conn.execute(text("PRAGMA table_info(live_room)"))
            if "remark" not in {column[1] for column in room_columns.all()}:
                await conn.execute(text("ALTER TABLE live_room ADD COLUMN remark VARCHAR(512)"))
            video_columns = await conn.execute(text("PRAGMA table_info(live_room_log_video)"))
            if "file_path" not in {column[1] for column in video_columns.all()}:
                await conn.execute(text("ALTER TABLE live_room_log_video ADD COLUMN file_path TEXT"))
            await _ensure_sqlite_defaults(conn)
            log_columns = await conn.execute(text("PRAGMA table_info(live_room_log)"))
            if "interrupted" not in {column[1] for column in log_columns.all()}:
                await conn.execute(text("ALTER TABLE live_room_log ADD COLUMN interrupted BOOLEAN NOT NULL DEFAULT 0"))


async def _ensure_sqlite_defaults(conn):
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
        if "live_room_log_old" in table_names:
            await conn.execute(text("DROP TABLE live_room_log_old"))
        return

    for index_name in (
        "ix_live_room_log_live_room_id",
        "ix_live_room_log_platform",
        "ix_live_room_log_del_flag",
    ):
        await conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
    await conn.execute(text("ALTER TABLE live_room_log RENAME TO live_room_log_old"))
    await conn.run_sync(Base.metadata.create_all)
    interrupted_value = "interrupted" if any(column["name"] == "interrupted" for column in columns) else "0"
    await conn.execute(text(f"""
        INSERT INTO live_room_log
            (id, live_room_id, platform, owner, title, start_live, end_live,
             live_time, user_num, total_user, create_time, del_flag, interrupted)
        SELECT
            id, live_room_id, platform, owner, title, start_live, end_live,
            live_time, user_num, total_user, COALESCE(create_time, CURRENT_TIMESTAMP), del_flag, {interrupted_value}
        FROM live_room_log_old
    """))
    await conn.execute(text("DROP TABLE live_room_log_old"))
