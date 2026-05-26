# Live Recorder

基于 FastAPI 的多直播平台单体录制平台，支持抖音、哔哩哔哩、斗鱼直播间管理、直播检测、后台监控录制、SQLite 持久化和 Redis 录制锁。

## 启动

```powershell
python -m pip install -r requirements.txt
python run.py
```

打开 `http://127.0.0.1:8000` 使用内嵌前端，接口文档在 `http://127.0.0.1:8000/docs`。

## 配置

主要配置在 `config.yaml`：

- `database.url`: 默认使用 `sqlite+aiosqlite:///./data/live_recorder.db`
- `redis`: Redis 地址、端口、密码和库编号
- `platforms`: 各平台 Cookie
- `transcode`: 后处理转码开关和显卡类型

Redis 未启动时，页面和 SQLite CRUD 仍可使用；启动录制监控需要 Redis 正常连接。
