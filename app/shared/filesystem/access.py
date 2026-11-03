"""识别本机请求，并校验文件目录访问条件。"""


from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def is_loopback(host):
    """判断主机名或 IP 是否指向本机回环地址。

    Args:
        host: 主机名或 IP 地址，允许为 None。

    Returns:
        localhost、回环 IP 和映射到回环 IPv4 的 IPv6 地址返回 True。
    """
    if host == "localhost":
        return True
    try:
        address = ip_address(host or "")
        return address.is_loopback or (address.version == 6 and address.ipv4_mapped is not None and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def check_directory_access(request: Request):
    """校验目录浏览请求来自本机及本机页面。

    Args:
        request: 待检查的 HTTP 请求。

    Raises:
        HTTPException: 客户端不是回环地址，或来源页面不属于本机。
    """
    if request.client is None or not is_loopback(request.client.host):
        raise HTTPException(status_code=403, detail="目录浏览仅允许从后端本机访问")
    for header in ("origin", "referer"):
        source = request.headers.get(header)
        if source:
            try:
                allowed = is_loopback(urlsplit(source).hostname)
            except ValueError:
                allowed = False
            if not allowed:
                raise HTTPException(status_code=403, detail="目录浏览仅允许从本机页面访问")
