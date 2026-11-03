"""为 HTTP 请求和后台任务提供异步数据库会话，并在异常时回滚。"""


from contextlib import asynccontextmanager
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


def get_session_factory(request: Request):
    """获取请求所属应用的异步数据库会话工厂。

    Args:
        request: 当前 HTTP 请求。

    Returns:
        挂载在 app.state.db 上的异步会话工厂。
    """
    return request.app.state.db


async def get_db(request: Request):
    """为 FastAPI 依赖注入提供数据库会话，异常时回滚。

    Args:
        request: 当前 HTTP 请求。

    Yields:
        在请求依赖使用结束后关闭的异步数据库会话。
    """
    async_session_factory = request.app.state.db

    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session(app):
    """通过异步上下文管理器为后台任务提供会话，异常时回滚。

    Args:
        app: 提供异步数据库会话工厂的应用实例。

    Yields:
        在退出上下文时关闭的异步数据库会话。
    """
    async_session_factory = app.state.db

    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
