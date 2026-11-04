"""配置平台请求共用的异步 HTTP 客户端、超时、连接池和证书信任。"""


import ssl

import httpx

try:
    import truststore  # type: ignore
except ImportError:
    truststore = None

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=15.0,
    read=60.0,
    write=60.0,
    pool=15.0,
)
DEFAULT_CONNECTION_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=100)

_client: httpx.AsyncClient | None = None


def start_client() -> httpx.AsyncClient:
    """在应用启动时创建共享客户端，重复调用时复用尚未关闭的实例。"""
    global _client
    if _client is None or _client.is_closed:
        # 证书上下文随客户端创建，避免导入模块时初始化网络资源。
        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if truststore else True
        _client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=DEFAULT_TIMEOUT,
            limits=DEFAULT_CONNECTION_LIMITS,
            verify=verify,
        )
    return _client


def get_client() -> httpx.AsyncClient:
    """获取当前应用的共享客户端。

    Raises:
        RuntimeError: 应用尚未启动或客户端已经关闭。
    """
    if _client is None or _client.is_closed:
        raise RuntimeError("平台 HTTP 客户端未启动或已关闭")
    return _client


async def close_client() -> None:
    """在平台请求任务结束后释放连接池，允许重复关闭。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
