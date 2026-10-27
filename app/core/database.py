
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base
from app.core.paths import ROOT_DIR

engine = None
AsyncSessionLocal = None


def resolve_database_url(db_url: str) -> str:
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        url = url.set(database=str(path.resolve()))
    return url.render_as_string(hide_password=False)


async def init_db(app, db_url: str):
    global engine
    global AsyncSessionLocal

    db_url = resolve_database_url(db_url)
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

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
            settings_columns = await conn.execute(text("PRAGMA table_info(recording_settings)"))
            settings_names = {column[1] for column in settings_columns.all()}
            for name, definition in (
                ("disk_protection_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("disk_min_free_gb", "INTEGER NOT NULL DEFAULT 5"),
                ("disk_stop_free_gb", "INTEGER NOT NULL DEFAULT 1"),
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
