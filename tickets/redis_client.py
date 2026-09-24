"""
One Valkey pool and one registered Lua script per worker process.

Module-level, so it is built once when the worker imports the app and then
reused for every request that worker serves. gunicorn must run with
preload_app = False: a pool created before fork would hand the same sockets
to every child, and concurrent replies would interleave into garbage.
"""
import redis
from django.conf import settings

# BlockingConnectionPool, not ConnectionPool. The plain pool raises
# MaxConnectionsError the instant it is full instead of waiting for a
# connection that frees up microseconds later.
_pool = redis.BlockingConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    timeout=2,
    decode_responses=True,
    socket_timeout=1.0,
    socket_connect_timeout=1.0,
    health_check_interval=30,
)

client = redis.Redis(connection_pool=_pool)

# Decrement and enqueue in one atomic step. Valkey is single-threaded and
# nothing else runs while a script runs, so two buyers can never take the
# same ticket. Splitting this into two calls would let DECR succeed and
# XADD fail, and that ticket would vanish: sold, but no order anywhere.
PURCHASE_LUA = """
local remaining = tonumber(redis.call('GET', KEYS[1]))
if remaining == nil then return -2 end
if remaining <= 0 then return -1 end
local left = redis.call('DECR', KEYS[1])
redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[5], '*',
  'order_id', ARGV[1], 'event_id', ARGV[2],
  'user_id',  ARGV[3], 'ts',       ARGV[4])
return left
"""

# register_script hashes the body locally and sends EVALSHA, falling back to
# EVAL once if Valkey has not seen it. Plain eval() would push the whole
# script over the wire on every single request.
purchase_script = client.register_script(PURCHASE_LUA)
