from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.live_checker import LiveChecker

router = APIRouter(prefix="/live", tags=["直播检测"])


class LiveCheckRequest(BaseModel):
    roomUrl: str


@router.post("/check")
async def check_live(req: LiveCheckRequest):
    try:
        result = await LiveChecker.check(req.roomUrl)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
