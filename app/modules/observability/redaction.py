import re
from urllib.parse import urlsplit


_urls = re.compile(r"(?:https?|rtmps?|rtsp|srt|mysql(?:\+[^:\s]+)?|postgresql(?:\+[^:\s]+)?)://[^\s<>\"']+", re.IGNORECASE)
_headers = re.compile(r"(?im)([\"']?(?:cookie|cookies|set-cookie|authorization|proxy-authorization)[\"']?\s*[:=]\s*)[^\r\n]*")
_values = re.compile(r"(?i)([\"']?(?:password|passwd|token|access_token|refresh_token|api[_-]?key|sessionid|session_id|mstoken|ttwid|signature|x-bogus|a_bogus)[\"']?\s*[:=]\s*)(?:\[REDACTED\]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&}\]]+)")


def configured_secrets(config):
    secrets = set()
    if isinstance(config, dict):
        for key, value in config.items():
            key = str(key)
            if any(part in key.lower() for part in ("cookie", "password", "token", "secret", "api_key")) and isinstance(value, str) and len(value) >= 4:
                secrets.add(value)
                if "cookie" in key.lower():
                    secrets.update(item.split("=", 1)[1].strip() for item in value.split(";") if "=" in item and len(item.split("=", 1)[1].strip()) >= 4)
            secrets.update(configured_secrets(value))
    return secrets


def redact(value, secrets=()):
    text = str(value)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")

    def url(match):
        try:
            host = urlsplit(match.group()).hostname
            return f"https://{host}/[REDACTED]" if host else "[URL REDACTED]"
        except ValueError:
            return "[URL REDACTED]"

    text = _urls.sub(url, text)
    text = re.sub(r"(/(?:api|live|crawler|docs)[^\s?\"']*)\?[^\s\"']+", lambda match: match[1] + "?[REDACTED]", text)
    text = _headers.sub(lambda match: match[1] + "[REDACTED]", text)
    return _values.sub(lambda match: match[1] + "[REDACTED]", text)


def export_safe(value, roots, secrets=()):
    if isinstance(value, dict):
        return {key: export_safe(item, roots, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [export_safe(item, roots, secrets) for item in value]
    if isinstance(value, str):
        text = redact(value, secrets)
        for root, replacement in sorted(roots, key=lambda item: len(item[0]), reverse=True):
            if root:
                text = re.sub(re.escape(root), lambda _: replacement, text, flags=re.IGNORECASE)
                text = re.sub(re.escape(root.replace("\\", "/")), lambda _: replacement, text, flags=re.IGNORECASE)
        return text
    return value
