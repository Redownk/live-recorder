# 构建前端，运行镜像中无需保留 Node.js 和 node_modules。
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.15.2-slim-trixie AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LIVE_RECORDER_DATA_DIR=/data \
    TZ=Asia/Shanghai

WORKDIR /app
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates ffmpeg tini tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# PyYAML 的纯 Python 实现避免依赖编译工具，也适用于尚无预编译包的 Python 版本。
RUN PYYAML_FORCE_LIBYAML=0 python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

COPY app/ ./app/
COPY run.py ./
COPY docker/ ./docker/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

RUN groupadd --gid 10001 recorder \
    && useradd --uid 10001 --gid recorder --no-create-home --home-dir /data recorder \
    && mkdir -p /data \
    && chown recorder:recorder /data
USER recorder

VOLUME ["/data"]
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/recording-status', timeout=3).close()"]

# tini 转发停止信号并回收子进程；入口脚本初始化持久化配置后替换自身。
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/docker/entrypoint.py"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
