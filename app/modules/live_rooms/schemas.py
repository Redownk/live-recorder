"""定义直播间创建、更新、查询和录制控制的请求与响应结构。"""


from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LiveRoomBase(BaseModel):
    platform: str = Field(..., examples=["DOUYIN"])
    room_id: str
    room_url: str | None = None
    sec_uid: str | None = None
    owner: str | None = None
    remark: str | None = Field(default=None, max_length=512)
    title: str | None = None
    avatar: str | None = None
    cover: str | None = None
    monitor_enabled: bool = True


class LiveRoomCreate(BaseModel):
    room_url: str
    remark: str | None = Field(default=None, max_length=512)
    monitor_enabled: bool = True


class LiveRoomUpdate(BaseModel):
    platform: str | None = None
    room_id: str | None = None
    room_url: str | None = None
    sec_uid: str | None = None
    owner: str | None = None
    remark: str | None = Field(default=None, max_length=512)
    title: str | None = None
    avatar: str | None = None
    cover: str | None = None
    monitor_enabled: bool | None = None


class LiveRoomOut(LiveRoomBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recording_settings_customized: bool = False
    last_live_time: datetime | None = None
    create_time: datetime
    update_time: datetime


class MonitorUpdate(BaseModel):
    monitor_enabled: bool


class RecordingStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disable_monitor: bool = Field(default=True, strict=True)


class RoomBackupEntry(BaseModel):
    """直播间备份条目，不携带数据库 ID、历史记录或平台凭据。"""

    platform: Literal["DOUYIN", "BILIBILI", "DOUYU"]
    room_id: str = Field(min_length=1, max_length=128)
    room_url: str | None = Field(default=None, max_length=512)
    sec_uid: str | None = Field(default=None, max_length=255)
    owner: str | None = Field(default=None, max_length=255)
    remark: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=512)
    avatar: str | None = Field(default=None, max_length=1024)
    cover: str | None = Field(default=None, max_length=1024)
    monitor_enabled: bool = Field(default=False, strict=True)

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("room_id", mode="before")
    @classmethod
    def normalize_room_id(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise ValueError("房间号不能包含控制字符")
        return value

    @field_validator("room_url", "avatar", "cover")
    @classmethod
    def validate_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("链接必须使用 HTTP 或 HTTPS")
        return value


class RoomBackupDocument(BaseModel):
    """Excel 解析后的内部直播间列表及原始行号。"""

    format: Literal["live-recorder-rooms"] = "live-recorder-rooms"
    version: Literal[1] = 1
    exported_at: datetime | None = None
    rooms: list[Any] = Field(max_length=5000)
    source_rows: list[int] | None = Field(default=None, exclude=True)


class RoomImportRequest(BaseModel):
    document: RoomBackupDocument
    enable_monitoring: bool = Field(default=False, strict=True)
