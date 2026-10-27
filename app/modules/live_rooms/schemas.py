from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    last_live_time: datetime | None = None
    create_time: datetime
    update_time: datetime


class MonitorUpdate(BaseModel):
    monitor_enabled: bool


class RecordingStop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disable_monitor: bool = Field(default=True, strict=True)
