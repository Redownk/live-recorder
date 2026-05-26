import asyncio
import boto3
from botocore.config import Config
from urllib.parse import urlsplit
from sqlalchemy import text
from app.core.session import get_db_session
from app.core.logger import get_logger


logger = get_logger(__name__)


async def load_oss_config(app):

    async with get_db_session(app) as db:

        result = await db.execute(text("""
            SELECT *
            FROM sys_oss_config
            WHERE status='0'
            LIMIT 1
        """))

        config = result.mappings().first()

    return config


def normalize_endpoint(config):
    endpoint = config["endpoint"]
    if not endpoint.startswith("http"):
        protocol = "https" if config["is_https"] == "Y" else "http"
        endpoint = f"{protocol}://{endpoint}"
    return endpoint


def detect_addressing_style(endpoint: str) -> str:
    host = urlsplit(endpoint).netloc.lower()

    if "aliyuncs.com" in host:
        return "virtual"

    if "minio" in host:
        return "path"

    return "path"


def build_oss_client_kwargs(config):
    endpoint = normalize_endpoint(config)
    addressing_style = detect_addressing_style(endpoint)

    return {
        "service_name": "s3",
        "endpoint_url": endpoint,
        "aws_access_key_id": config["access_key"],
        "aws_secret_access_key": config["secret_key"],
        "region_name": config["region"] or "oss-general",
        "config": Config(
            s3={
                "addressing_style": addressing_style,
                "payload_signing_enabled": False,
            },
            signature_version="s3",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={'max_attempts': 3, 'mode': 'standard'}  # 增加自动重试
        ),
    }


def build_file_url(config, bucket, object_name):
    if config["domain"]:
        return f"{config['domain'].rstrip('/')}/{object_name}"

    endpoint = normalize_endpoint(config)
    addressing_style = detect_addressing_style(endpoint)
    parsed = urlsplit(endpoint)

    if addressing_style == "virtual":
        return f"{parsed.scheme}://{bucket}.{parsed.netloc}/{object_name}"

    return f"{parsed.scheme}://{parsed.netloc}/{bucket}/{object_name}"


async def upload_file(app, file_path):

    import os

    config = await load_oss_config(app)

    if not config:
        logger.warning("未找到OSS配置")
        return None

    client_kwargs = build_oss_client_kwargs(config)

    bucket = config["bucket_name"]
    prefix = config["prefix"] or ""

    file_name = os.path.basename(file_path)

    object_name = f"{prefix}/{file_name}" if prefix else file_name

    def _upload():
        client = boto3.client(**client_kwargs)
        client.upload_file(file_path, bucket, object_name)

    await asyncio.to_thread(_upload)

    return build_file_url(config, bucket, object_name)
