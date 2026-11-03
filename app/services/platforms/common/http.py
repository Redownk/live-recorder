"""配置平台请求共用的异步 HTTP 客户端、超时、连接池和证书信任。"""


import httpx

try:
    import ssl
    import truststore  # type: ignore
except ImportError:
    ssl = None
    truststore = None
    _ssl_context = True
else:
    _ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=15.0,
    read=60.0,
    write=60.0,
    pool=15.0,
)
DEFAULT_CONNECTION_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=100)

client = httpx.AsyncClient(
    http2=True,
    follow_redirects=True,
    timeout=DEFAULT_TIMEOUT,
    limits=DEFAULT_CONNECTION_LIMITS,
    verify=_ssl_context
)
