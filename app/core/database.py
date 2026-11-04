"""解析数据库路径，创建应用级引擎和会话工厂，并执行版本化升级。"""


from pathlib import Path
import asyncio

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.paths import ROOT_DIR
from app.migrations.runner import backup_before_upgrade, upgrade_database


def resolve_database_url(db_url: str) -> str:
    """将 SQLite 相对路径解析到持久化数据目录。

    Args:
        db_url: SQLAlchemy 数据库连接地址。

    Returns:
        解析后的连接地址；内存数据库及其他数据库类型保持原值语义。
    """
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database).expanduser()
        if not path.is_absolute():
            path = ROOT_DIR / path
        url = url.set(database=str(path.resolve()))
    return url.render_as_string(hide_password=False)


async def init_db(app, db_url: str):
    """初始化数据库引擎、会话工厂和应用所需的表结构。

    Args:
        app: 接收数据库引擎和会话工厂的应用实例。
        db_url: SQLAlchemy 异步数据库连接地址。
    """
    db_url = resolve_database_url(db_url)
    url = make_url(db_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(backup_before_upgrade, Path(url.database))

    engine = create_async_engine(
        db_url,
        pool_pre_ping=True,
        echo=False
    )

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False
    )

    app.state.engine = engine
    app.state.db = session_factory

    try:
        await upgrade_database(engine)
    except BaseException:
        # init_db 也可独立用于自检；升级失败时仍须释放连接池。
        await engine.dispose()
        raise
