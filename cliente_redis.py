import redis

from config import configuracao_redis

cliente = redis.Redis(**configuracao_redis())
