"""提供直播间 Excel 下载、导入预览和批量导入接口。"""

import asyncio
from datetime import datetime
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.session import get_db
from app.modules.live_rooms.schemas import RoomImportRequest
from app.modules.live_rooms.transfer import export_rooms, import_rooms, import_summary, plan_import
from app.modules.live_rooms.excel import CONTENT_TYPE, MAX_FILE_BYTES, create_workbook, parse_workbook


router = APIRouter(prefix="/rooms")
logger = get_logger(__name__)


@router.get("/export")
async def export_room_list(db: AsyncSession = Depends(get_db)):
    data = await export_rooms(db)
    filename = f"live-rooms-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    content = await asyncio.to_thread(create_workbook, data["rooms"])
    return Response(content, media_type=CONTENT_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


async def read_excel_request(request):
    """限量读取上传正文，并在线程中解析 Excel，避免阻塞请求事件循环。"""
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="文件不能超过 5 MiB")
        content.extend(chunk)
    try:
        return await asyncio.to_thread(parse_workbook, bytes(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (BadZipFile, InvalidFileException, ParseError, OSError, KeyError, TypeError, IndexError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="无法读取 Excel，请使用未加密的 .xlsx 文件") from exc


@router.post("/import/preview")
async def preview_room_import(request: Request, db: AsyncSession = Depends(get_db)):
    document = await read_excel_request(request)
    rows, _ = await plan_import(document, db)
    return import_summary(rows)


@router.post("/import")
async def import_room_list(request: Request, enable_monitoring: bool = Query(default=False), db: AsyncSession = Depends(get_db)):
    payload = RoomImportRequest(document=await read_excel_request(request), enable_monitoring=enable_monitoring)
    manager = request.app.state.recording_settings
    # 与配置写入共用锁，串行处理批量导入并在提交后唤醒直播间扫描。
    async with manager.write_lock:
        result = await import_rooms(payload, db)
        if result["imported"]:
            manager.changed.set()
    logger.info("直播间导入完成：新增 %s，重复 %s，无效 %s", result["imported"], result["duplicate"], result["invalid"])
    return result
