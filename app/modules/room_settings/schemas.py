from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.settings.service import RecordingOptions


class RoomRecordingOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    save_path: str | None = Field(default=None, min_length=1, max_length=1024)
    filename_template: str | None = Field(default=None, min_length=1, max_length=255)
    check_interval_seconds: int | None = Field(default=None, ge=1, le=86400, strict=True)
    quality: Literal["best", "high", "medium", "low"] | None = None
    segment_minutes: int | None = Field(default=None, ge=0, le=1440, strict=True)

    @model_validator(mode="after")
    def validate_shared_options(self):
        values = self.model_dump(exclude_none=True)
        normalized = RecordingOptions.model_validate(values)
        for field in values:
            setattr(self, field, getattr(normalized, field))
        return self
