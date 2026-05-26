
from fastapi import APIRouter, HTTPException, Request
from app.services.crawler_manager import crawler_manager

router = APIRouter(prefix="/crawler")


@router.post("/start")
async def start(request: Request):
    if not getattr(request.app.state, "redis_connected", False):
        raise HTTPException(status_code=503, detail="Redis 未连接，无法启动录制监控")
    result = await crawler_manager.start()
    return {"msg": result}


@router.post("/stop")
async def stop():
    result = await crawler_manager.stop()
    return {"msg": result}


@router.get("/status")
async def status():
    result = crawler_manager.status()
    return {"running": result}
