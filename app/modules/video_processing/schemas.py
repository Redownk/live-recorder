from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.settings.service import safe_filename


ENCODERS = {
    "copy": "copy", "libx264": "H.264 (x264)", "h264_qsv": "H.264 (Intel QSV)",
    "h264_nvenc": "H.264 (NVIDIA NVENC)", "h264_amf": "H.264 (AMD AMF)",
    "h264_videotoolbox": "H.264 (Apple)", "libx265": "H.265 (x265)",
    "hevc_qsv": "H.265 (Intel QSV)", "hevc_nvenc": "H.265 (NVIDIA NVENC)",
    "hevc_amf": "H.265 (AMD AMF)", "hevc_videotoolbox": "H.265 (Apple)",
}


class ProcessingOptions(BaseModel):
    mode: Literal["transcode", "merge"]
    files: list[str] = Field(min_length=1, max_length=100)
    encoder: Literal[tuple(ENCODERS)] = "libx264"
    preset: Literal["default", "quality", "fast"] = "default"
    container: Literal["mp4", "mkv", "ts"] = "mp4"
    save_original: bool = True
    output_directory: str = Field(default="", max_length=1024)
    output_name: str = Field(default="merged", min_length=1, max_length=180)
    existing: Literal["skip", "overwrite"] = "skip"
    remove_source: bool = False
    keep_metadata: bool = True
    merge_subtitles: bool = False

    @model_validator(mode="after")
    def validate_options(self):
        if self.mode == "merge" and len(self.files) < 2:
            raise ValueError("合并至少需要两个视频文件")
        if self.mode == "merge" and self.remove_source:
            raise ValueError("合并不会删除源文件")
        if not self.save_original and not self.output_directory.strip():
            raise ValueError("请选择输出目录")
        if self.output_name != safe_filename(self.output_name) or self.output_name in (".", ".."):
            raise ValueError("输出文件名不能包含目录分隔符或非法字符")
        if any(len(path) > 1024 or not path.strip() or any(ord(c) < 32 for c in path) for path in self.files):
            raise ValueError("视频路径无效")
        return self
