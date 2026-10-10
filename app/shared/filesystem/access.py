from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        address = ip_address(host or "")
        return address.is_loopback or (address.version == 6 and address.ipv4_mapped is not None and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def check_directory_access(request: Request):
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
