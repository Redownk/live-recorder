import uuid
import redis
import time


class RedisLock:
    def __init__(self, redis_client: redis.Redis, key: str, expire: int):
        self.redis = redis_client
        self.key = key
        self.expire = expire
        self.value = str(uuid.uuid4())

    def acquire(self) -> bool:
        """
        尝试加锁
        """
        return self.redis.set(
            self.key,
            self.value,
            nx=True,
            ex=self.expire
        )

    def renew(self):
        """
        续期（仅当自己持有锁时）
        """
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        self.redis.eval(lua, 1, self.key, self.value, self.expire)

    def release(self):
        """
        释放锁（仅当自己持有锁时）
        """
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        self.redis.eval(lua, 1, self.key, self.value)