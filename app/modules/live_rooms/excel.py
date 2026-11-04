"""读写直播间 Excel 表格，保留文本编号并校验导入单元格。"""

from io import BytesIO
import math
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.modules.live_rooms.schemas import RoomBackupDocument


CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_FILE_BYTES = 5 * 1024 * 1024
COLUMNS = (
    ("platform", "平台", 16), ("room_id", "房间号", 26), ("owner", "主播", 22),
    ("remark", "备注", 36), ("room_url", "直播间链接", 44),
    ("monitor_enabled", "监控开关", 14), ("sec_uid", "用户标识", 30),
    ("avatar", "头像链接", 36), ("cover", "封面链接", 36),
)
PLATFORMS = {"DOUYIN": "抖音", "BILIBILI": "哔哩哔哩", "DOUYU": "斗鱼"}
PLATFORM_CODES = {label: code for code, label in PLATFORMS.items()}
FIELD_COLUMNS = {field: get_column_letter(index) for index, (field, _, _) in enumerate(COLUMNS, 1)}


def create_workbook(rooms):
    """将直播间信息写为带表头、筛选和填写说明的 Excel 文件。

    Args:
        rooms: 按字段名组织的直播间字典列表。

    Returns:
        XLSX 文件的原始字节。
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "直播间"
    sheet.freeze_panes = "A2"
    sheet.append([label for _, label, _ in COLUMNS])
    for index, (_, _, width) in enumerate(COLUMNS, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    # 列默认格式也设为文本，便于在导出文件的空白行中继续填写编号。
    for field in ("room_id", "sec_uid"):
        sheet.column_dimensions[FIELD_COLUMNS[field]].number_format = "@"
    for cell in sheet[1]:
        cell.font = Font(name="微软雅黑", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="22766A")
        cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 26
    for row_number, room in enumerate(rooms, start=2):
        values = []
        for field, _, _ in COLUMNS:
            value = room.get(field)
            if field == "platform":
                value = PLATFORMS.get(value, value)
            elif field == "monitor_enabled":
                value = "启用" if value else "暂停"
            values.append(None if value is None else str(value))
        sheet.append(values)
        for cell in sheet[row_number]:
            # 明确写入字符串，避免编号变成科学计数法或文本被识别为公式。
            if cell.value is not None:
                cell.data_type = "s"
            cell.number_format = "@"
            cell.font = Font(name="微软雅黑", size=11)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{sheet.max_row}"
    for field, options in (("platform", "抖音,哔哩哔哩,斗鱼"), ("monitor_enabled", "启用,暂停")):
        column = FIELD_COLUMNS[field]
        validation = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True)
        validation.errorTitle, validation.error = "填写内容不正确", "请选择下拉列表中的值"
        validation.showErrorMessage = True
        sheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}5001")
    notes = workbook.create_sheet("填写说明")
    for row in (
        ("字段", "填写说明"),
        ("必填列", "平台、房间号。其余列可留空，列顺序可以调整。"),
        ("平台", "抖音、哔哩哔哩、斗鱼，也支持 DOUYIN、BILIBILI、DOUYU。"),
        ("房间号和用户标识", "请保持文本格式，避免 Excel 丢失前导零或超过 15 位的编号。"),
        ("监控开关", "启用或暂停。导入时默认暂停监控，可勾选恢复文件中的监控设置。"),
        ("重复记录", "相同平台和房间号只新增一次，已有直播间的设置保持原值。"),
        ("文件限制", "使用 .xlsx 格式，最多 5000 条记录、文件不超过 5 MiB。空白行会跳过。"),
        ("单元格", "请填写普通文本或数值，公式单元格不能导入。"),
    ):
        notes.append(row)
    notes.column_dimensions["A"].width = 24
    notes.column_dimensions["B"].width = 90
    for row in notes:
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        notes.row_dimensions[row[0].row].height = 32
    output = BytesIO()
    try:
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()


def _cell_value(cell, field):
    if cell.data_type == "f":
        raise ValueError("不支持公式单元格，请将公式粘贴为值后导入")
    value = cell.value
    if value is None:
        return False if field == "monitor_enabled" else None
    if field == "monitor_enabled":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"启用", "开启", "是", "true", "1"}:
            return True
        if normalized in {"暂停", "关闭", "否", "false", "0", ""}:
            return False
        raise ValueError("监控开关请填写启用或暂停")
    if field in {"room_id", "sec_uid"} and isinstance(value, (int, float)):
        if isinstance(value, bool) or not math.isfinite(value) or value != int(value) or abs(value) >= 10**15:
            raise ValueError("房间号和用户标识必须为完整编号；长编号请使用文本格式")
        value = str(int(value))
    value = str(value).strip()
    return PLATFORM_CODES.get(value, value) if field == "platform" else value or None


def parse_workbook(content):
    """解析 Excel 表头及数据，保留原始行号和逐行错误。

    Args:
        content: XLSX 文件的原始字节。

    Returns:
        可供导入预览和写入复用的内部文档。

    Raises:
        ValueError: 文件过大、列缺失、表头重复或数据行超出限制。
    """
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("文件不能超过 5 MiB")
    with ZipFile(BytesIO(content)) as archive:
        if len(archive.infolist()) > 1000 or sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024:
            raise ValueError("Excel 文件解压后的内容过大")
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    try:
        sheet = workbook["直播间"] if "直播间" in workbook.sheetnames else workbook.worksheets[0]
        if (sheet.max_column or 0) > 64 or (sheet.max_row or 0) > 5001:
            raise ValueError("Excel 最多支持 5000 行数据和 64 列")
        aliases = {alias: field for field, label, _ in COLUMNS for alias in (field, label)}
        header = next(sheet.iter_rows(min_row=1, max_row=1, max_col=64))
        columns = {}
        for index, cell in enumerate(header):
            name = str(cell.value or "").strip()
            field = aliases.get(name)
            if field:
                if field in columns.values():
                    raise ValueError(f"表头重复：{name}")
                columns[index] = field
        if not {"platform", "room_id"}.issubset(columns.values()):
            raise ValueError("Excel 第一行必须包含平台和房间号两列")
        rooms, source_rows = [], []
        for row_number, cells in enumerate(sheet.iter_rows(min_row=2, max_row=sheet.max_row or 5002, max_col=max(columns) + 1), 2):
            if all(cells[index].value in (None, "") for index in columns):
                continue
            try:
                entry = {field: _cell_value(cells[index], field) for index, field in columns.items()}
            except ValueError as exc:
                entry = {"__import_error__": str(exc)}
            rooms.append(entry)
            source_rows.append(row_number)
            if len(rooms) > 5000:
                raise ValueError("每次最多导入 5000 条直播间")
        return RoomBackupDocument(rooms=rooms, source_rows=source_rows)
    finally:
        workbook.close()
