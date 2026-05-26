# app/core/session.py

from contextlib import asynccontextmanager
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


def get_session_factory(request: Request):
    """
    从 app.state 中获取 AsyncSessionLocal
    """
    return request.app.state.db


# ==============================
# FastAPI 依赖注入（异步）
# ==============================
async def get_db(request: Request):
    """
    FastAPI 依赖注入使用
    用法:
        db: AsyncSession = Depends(get_db)
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


# ==============================
# 后台任务使用（异步）
# ==============================
@asynccontextmanager
async def get_db_session(app):
    """
    给后台任务使用（例如 crawler_worker）
    用法:
        async with get_db_session(app) as db:
            ...
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