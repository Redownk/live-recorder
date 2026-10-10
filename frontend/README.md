# Live Recorder Frontend

独立的 Vue 3 管理界面，后端使用仓库根目录的 FastAPI 项目。

## 本地开发

```powershell
npm ci
npm run dev
```

默认前端地址：`http://127.0.0.1:5173`。后端需要单独启动，默认端口为 8000。

接口保持原有路径：新增、查询、编辑、删除与监控开关使用 `/api/rooms`；
日志、视频使用 `/api/logs`、`/api/videos`；监控控制使用 `/crawler/start`、`/crawler/stop`、`/crawler/status`。
添加直播间只提交 URL 和监控开关，由后端调用对应平台 checker 获取房间信息。

## 环境变量

在本目录创建 `.env.local`，可参考 `.env.example`：

```dotenv
API_PROXY_TARGET=http://127.0.0.1:8000
VITE_API_BASE_URL=
```

`API_PROXY_TARGET` 配置开发和本地预览代理；`VITE_API_BASE_URL` 配置浏览器请求地址。
默认留空，使用同源代理。环境变量变更后重启开发服务器；生产请求地址变更后重新构建。
不要在 `VITE_` 变量中存放密码或 Cookie，它们会进入浏览器构建产物。

## 构建与部署

```powershell
npm run build
npm run preview
```

构建产物在 `dist/`，可由 Nginx 或其他静态服务器独立部署。
`preview` 仅用于本地验证构建，默认端口为 4173。

推荐生产前端与 API 使用同一域名：静态服务器将 `/api/`、`/crawler/`、`/live/`、`/actuator/`
代理到 FastAPI，其余前端路由（例如 `/rooms`）使用 `index.html` 回退。Nginx 示例：

```nginx
server {
    listen 80;
    root /srv/live-recorder/frontend/dist;
    index index.html;

    location ~ ^/(api|crawler|live|actuator)(/|$) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

若前后端使用不同域名，构建前配置 `VITE_API_BASE_URL=https://api.example.com`，
后端设置环境变量 `CORS_ORIGINS` 为前端来源地址，多个来源用逗号分隔。
FastAPI 默认允许 `http://localhost:5173` 和 `http://127.0.0.1:5173`。

## 浏览器回归验证

```powershell
npx playwright install chromium
npm run test:e2e
```

测试使用模拟 API，不访问真实直播平台，不写入项目数据库，不启动录制。
覆盖桌面与手机视口、房间操作、路由筛选和接口错误提示。
