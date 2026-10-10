
from fastapi import APIRouter
from app.modules.recording.crawler import crawler_manager

router = APIRouter(prefix="/crawler")


@router.post("/start")
async def start():
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
