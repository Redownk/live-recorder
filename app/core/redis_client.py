
import redis.asyncio as redis
from app.core.config import local_config


async def create_redis_client():
    redis_config = local_config.get("redis", {})

    if not redis_config:
        raise RuntimeError("Redis config not found in config.yaml")

    host = redis_config.get("host")
    port = redis_config.get("port")
    password = redis_config.get("password")
    database = redis_config.get("database", 0)
    timeout = redis_config.get("timeout", 10000) / 1000

    return redis.Redis(
        host=host,
        port=port,
        password=password,
        db=database,
        socket_timeout=timeout,
        decode_responses=True
    )


redis_client = None


async def init_redis():
    global redis_client
    redis_client = await create_redis_client()
