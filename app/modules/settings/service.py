import asyncio
import re
import tempfile
from datetime import datetime
from pathlib import Path
from string import Formatter
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import ROOT_DIR
from app.core.session import get_db_session
from app.models import RecordingSettings


DEFAULT_FILENAME_TEMPLATE = "{platform}_{owner}_{timestamp}"
TEMPLATE_FIELDS = {"platform", "owner", "remark", "room_id", "title", "date", "time", "timestamp", "record_id"}
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f\']')


class RecordingOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    save_path: str = Field(default="./record", min_length=1, max_length=1024)
    filename_template: str = Field(default=DEFAULT_FILENAME_TEMPLATE, min_length=1, max_length=255)
    check_interval_seconds: int = Field(default=5, ge=1, le=86400, strict=True)

    @field_validator("save_path")
    @classmethod
    def validate_path(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("保存路径不能为空或包含控制字符")
        return value

    @field_validator("filename_template")
    @classmethod
    def validate_template(cls, value):
        value = value.strip()
        if not value or "\\" in value or any(ord(char) < 32 for char in value):
            raise ValueError("命名规则不能为空，目录层级请使用 /，不能包含控制字符")
        if re.match(r"^[A-Za-z]:", value) or any(part.strip() in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("命名规则必须是相对路径，不能包含空目录、. 或 ..")
        try:
            fields = list(Formatter().parse(value))
        except ValueError as exc:
            raise ValueError("命名规则的花括号不匹配") from exc
        for _, field, spec, conversion in fields:
            if field is not None and (field not in TEMPLATE_FIELDS or spec or conversion):
                raise ValueError("不支持的命名变量或格式")
        return value


def resolve_save_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def ensure_writable_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path):
        pass


def safe_filename(value: str) -> str:
    value = INVALID_FILENAME_CHARS.sub("_", str(value)).strip(" .")
    value = value.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .") or "recording"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        value = "_" + value
    return value


def build_filename(template: str, room, live_info, start_time: datetime, record_id: str) -> str:
    values = {
        "platform": room["platform"],
        "owner": live_info.get("owner") or room.get("owner") or "unknown",
        "remark": str(room.get("remark") or "").strip() or "未备注",
        "room_id": room["room_id"],
        "title": live_info.get("title") or "untitled",
        "date": start_time.strftime("%Y%m%d"),
        "time": start_time.strftime("%H%M%S"),
        "timestamp": start_time.strftime("%Y%m%d%H%M%S"),
        "record_id": record_id,
    }
    # Split the template before substitution so metadata cannot create directories.
    parts = [safe_filename(part.format_map(values)) for part in template.split("/")]
    return "/".join(parts)


class RecordingSettingsManager:
    def __init__(self, settings: RecordingOptions):
        self.settings = settings
        self.changed = asyncio.Event()
        self.write_lock = asyncio.Lock()
        self.claimed_output_prefixes: set[Path] = set()

    async def save(self, app, settings: RecordingOptions):
        async with self.write_lock:
            path = resolve_save_path(settings.save_path)
            await asyncio.to_thread(ensure_writable_directory, path)
            async with get_db_session(app) as db:
                record = await db.get(RecordingSettings, 1)
                if record is None:
                    record = RecordingSettings(id=1, **settings.model_dump())
                    db.add(record)
                else:
                    for key, value in settings.model_dump().items():
                        setattr(record, key, value)
                await db.commit()
            self.settings = settings
            self.changed.set()


async def init_recording_settings(app):
    async with get_db_session(app) as db:
        record = await db.get(RecordingSettings, 1)
        settings = RecordingOptions.model_validate(record) if record is not None else RecordingOptions()
    app.state.recording_settings = RecordingSettingsManager(settings)


async def create_output_prefix(app, room, live_info, start_time: datetime) -> str:
    manager = app.state.recording_settings
    settings = manager.settings
    directory = resolve_save_path(settings.save_path)
    name = build_filename(settings.filename_template, room, live_info, start_time, uuid4().hex)
    output = (directory / name).resolve()
    if not output.is_relative_to(directory):
        raise ValueError("录制路径不能超出保存目录")
    await asyncio.to_thread(ensure_writable_directory, output.parent)
    output = output.resolve()
    if not output.is_relative_to(directory):
        raise ValueError("录制路径不能超出保存目录")
    existing_output = re.compile(re.escape(output.name) + r"(?:\.(?:ts|flv|mp4)|_\d+\.(?:ts|flv)|_filelist\.txt)$", re.IGNORECASE)
    if output in manager.claimed_output_prefixes or any(existing_output.fullmatch(path.name) for path in output.parent.iterdir()):
        raise FileExistsError(f"录制文件名已被使用，请调整命名规则以区分录制: {output}")
    # Claim before returning so concurrent recordings cannot share a prefix.
    manager.claimed_output_prefixes.add(output)
    return str(output)
