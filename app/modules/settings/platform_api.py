"""提供平台 Cookie 配置状态及不回显凭据的保存、清除接口。"""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import yaml

from app.core.logger import get_logger
from app.modules.settings.platforms import PLATFORM_NAMES, cookie_status, normalize_cookie, save_platform_cookie


router = APIRouter(prefix="/platforms")
logger = get_logger(__name__)
Platform = Literal["douyin", "bilibili", "douyu"]


@router.get("")
async def platform_cookie_status():
    return JSONResponse({"platforms": [cookie_status(platform) for platform in PLATFORM_NAMES]},
                        headers={"Cache-Control": "no-store"})


async def persist_cookie(platform, cookie):
    try:
        state = await asyncio.to_thread(save_platform_cookie, platform, cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, yaml.YAMLError):
        # YAML 解析异常可能携带配置行内容，因此不把异常详情写入日志或响应。
        logger.warning("平台 Cookie 保存失败 platform=%s", platform)
        raise HTTPException(status_code=400, detail="平台配置保存失败，请检查配置文件和写入权限") from None
    logger.info("平台 Cookie %s platform=%s", "已保存" if state["configured"] else "已清除", platform)
    return JSONResponse(state, headers={"Cache-Control": "no-store"})


@router.put("/{platform}/cookie")
async def update_platform_cookie(platform: Platform, request: Request):
    # 显式校验请求，避免默认校验错误响应将敏感输入作为 input 字段回显。
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > 65536:
            raise HTTPException(status_code=413, detail="Cookie 请求内容过大")
        content.extend(chunk)
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="请求必须为包含 cookie 文本的 JSON 对象") from None
    if not isinstance(payload, dict) or set(payload) != {"cookie"} or not isinstance(payload["cookie"], str):
        raise HTTPException(status_code=400, detail="请求必须为包含 cookie 文本的 JSON 对象")
    try:
        cookie = normalize_cookie(payload["cookie"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not cookie:
        raise HTTPException(status_code=400, detail="请输入 Cookie，清除已保存内容请使用清除操作")
    return await persist_cookie(platform, cookie)


@router.delete("/{platform}/cookie")
async def clear_platform_cookie(platform: Platform):
    return await persist_cookie(platform, "")
