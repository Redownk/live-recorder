"""版本 3：删除标题列，并将旧文件名模板中的标题改为备注。"""

from sqlalchemy import text


async def upgrade(connection):
    """移除直播间和录制历史标题列，并迁移旧文件名模板。"""
    for table in ("live_room", "live_room_log"):
        result = await connection.execute(text(f"PRAGMA table_info({table})"))
        if "title" in {column[1] for column in result.all()}:
            await connection.execute(text(f"ALTER TABLE {table} DROP COLUMN title"))
    for table in ("recording_settings", "room_recording_settings"):
        await connection.execute(text(f"""
            UPDATE {table} SET filename_template=REPLACE(filename_template, '{{title}}', '{{remark}}')
            WHERE INSTR(filename_template, '{{title}}') > 0
        """))
