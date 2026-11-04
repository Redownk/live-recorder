"""版本 1：建立初始表结构快照，兼容尚无版本记录的历史数据库。"""

from sqlalchemy import text

# 固定本版本发布时的结构，后续模型变化必须通过新增迁移实现。
STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS live_room (
    id INTEGER NOT NULL,
    platform VARCHAR(32) NOT NULL,
    room_id VARCHAR(128) NOT NULL,
    room_url VARCHAR(512),
    sec_uid VARCHAR(255),
    owner VARCHAR(255),
    remark VARCHAR(512),
    avatar VARCHAR(1024),
    cover VARCHAR(1024),
    monitor_enabled BOOLEAN DEFAULT 1 NOT NULL,
    last_live_time DATETIME,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    del_flag INTEGER DEFAULT 0 NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS live_room_log (
    id INTEGER NOT NULL,
    live_room_id INTEGER NOT NULL,
    platform VARCHAR(32) NOT NULL,
    owner VARCHAR(255),
    start_live DATETIME,
    end_live DATETIME,
    interrupted BOOLEAN DEFAULT 0 NOT NULL,
    health_restart_count INTEGER DEFAULT 0 NOT NULL,
    health_last_error TEXT,
    live_time INTEGER,
    user_num INTEGER,
    total_user VARCHAR(64),
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    del_flag INTEGER DEFAULT 0 NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS live_room_log_video (
    id INTEGER NOT NULL,
    tenant_id VARCHAR(32) NOT NULL,
    live_room_id INTEGER NOT NULL,
    live_room_log_id INTEGER NOT NULL,
    file_name VARCHAR(512) NOT NULL,
    file_url TEXT,
    file_path TEXT,
    file_size INTEGER,
    duration INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    del_flag INTEGER DEFAULT 0 NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS live_room_stats (
    id INTEGER NOT NULL,
    live_room_id INTEGER NOT NULL,
    live_room_log_id INTEGER NOT NULL,
    online_count VARCHAR(64),
    like_count VARCHAR(64),
    watch_user_count VARCHAR(64),
    collect_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS recording_settings (
    id INTEGER NOT NULL,
    save_path VARCHAR(1024) NOT NULL,
    filename_template VARCHAR(255) NOT NULL,
    check_interval_seconds INTEGER NOT NULL,
    quality VARCHAR(16) DEFAULT 'best' NOT NULL,
    segment_minutes INTEGER DEFAULT 0 NOT NULL,
    disk_protection_enabled BOOLEAN DEFAULT 1 NOT NULL,
    disk_min_free_gb INTEGER DEFAULT 5 NOT NULL,
    disk_stop_free_gb INTEGER DEFAULT 1 NOT NULL,
    health_check_enabled BOOLEAN DEFAULT 1 NOT NULL,
    health_startup_timeout_seconds INTEGER DEFAULT 60 NOT NULL,
    health_stall_timeout_seconds INTEGER DEFAULT 60 NOT NULL,
    health_max_restarts INTEGER DEFAULT 3 NOT NULL,
    PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS room_recording_settings (
    room_id INTEGER NOT NULL,
    save_path VARCHAR(1024),
    filename_template VARCHAR(255),
    check_interval_seconds INTEGER,
    quality VARCHAR(16),
    segment_minutes INTEGER,
    PRIMARY KEY (room_id)
)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_del_flag ON live_room (del_flag)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_monitor_enabled ON live_room (monitor_enabled)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_platform ON live_room (platform)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_room_id ON live_room (room_id)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_del_flag ON live_room_log (del_flag)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_live_room_id ON live_room_log (live_room_id)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_platform ON live_room_log (platform)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_video_del_flag ON live_room_log_video (del_flag)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_video_live_room_id ON live_room_log_video (live_room_id)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_log_video_live_room_log_id ON live_room_log_video (live_room_log_id)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_stats_live_room_id ON live_room_stats (live_room_id)""",
    """CREATE INDEX IF NOT EXISTS ix_live_room_stats_live_room_log_id ON live_room_stats (live_room_log_id)""",
)


async def upgrade(connection):
    """创建缺失的业务表和索引，不覆盖已有记录。"""
    for statement in STATEMENTS:
        await connection.execute(text(statement))
