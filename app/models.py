from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecordingSettings(Base):
    __tablename__ = "recording_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    save_path: Mapped[str] = mapped_column(String(1024))
    filename_template: Mapped[str] = mapped_column(String(255))
    check_interval_seconds: Mapped[int] = mapped_column(Integer)
    disk_protection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    disk_min_free_gb: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    disk_stop_free_gb: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    health_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    health_startup_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default=text("60"))
    health_stall_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default=text("60"))
    health_max_restarts: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))


class LiveRoom(Base):
    __tablename__ = "live_room"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    room_id: Mapped[str] = mapped_column(String(128), index=True)
    room_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sec_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cover: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"), index=True)
    last_live_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=text("CURRENT_TIMESTAMP"))
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, server_default=text("CURRENT_TIMESTAMP"))
    del_flag: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), index=True)


class LiveRoomLog(Base):
    __tablename__ = "live_room_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    live_room_id: Mapped[int] = mapped_column(Integer, index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_live: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_live: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    health_restart_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    health_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=text("CURRENT_TIMESTAMP"))
    del_flag: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), index=True)


class LiveRoomStats(Base):
    __tablename__ = "live_room_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    live_room_id: Mapped[int] = mapped_column(Integer, index=True)
    live_room_log_id: Mapped[int] = mapped_column(Integer, index=True)
    online_count: Mapped[str | None] = mapped_column(String(64), nullable=True)
    like_count: Mapped[str | None] = mapped_column(String(64), nullable=True)
    watch_user_count: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collect_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=text("CURRENT_TIMESTAMP"))


class LiveRoomLogVideo(Base):
    __tablename__ = "live_room_log_video"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), default="000000")
    live_room_id: Mapped[int] = mapped_column(Integer, index=True)
    live_room_log_id: Mapped[int] = mapped_column(Integer, index=True)
    file_name: Mapped[str] = mapped_column(String(512))
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=text("CURRENT_TIMESTAMP"))
    del_flag: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), index=True)
