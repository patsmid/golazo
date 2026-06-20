from upstash_redis import Redis
from app.config import REDIS_URL, REDIS_TOKEN
import json

redis_client = Redis(url=REDIS_URL, token=REDIS_TOKEN)

def cache_get(key: str):
    val = redis_client.get(key)
    if val:
        return json.loads(val)
    return None

def cache_set(key: str, data, ttl_seconds: int = 7200):
    redis_client.set(key, json.dumps(data), ex=ttl_seconds)

def cache_delete(key: str):
    redis_client.delete(key)
