"""'Once per N seconds' limiter that works across many servers when Redis is configured."""
import time

from flask import current_app

_redis = None
_local = {}


def _client():
    global _redis
    url = current_app.config.get("REDIS_URL")
    if not url:
        return None
    if _redis is None:
        import redis

        _redis = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
    return _redis


def allow(key, seconds):
    """True if `key` may act now (and starts its cooldown); False if it must wait."""
    r = _client()
    if r is not None:
        try:
            return bool(r.set(f"cd:{key}", 1, nx=True, ex=int(seconds)))
        except Exception:
            pass  # Redis hiccup: fall back to this server's own memory rather than blocking chat
    now = time.monotonic()
    if len(_local) > 100000:
        _local.clear()
    if now - _local.get(key, -1e9) >= seconds:
        _local[key] = now
        return True
    return False


_local_hits = {}


def within_limit(key, limit, window):
    """True if `key` has made fewer than `limit` calls in the current `window` seconds.
    Shared across servers via Redis; falls back to bounded per-process memory."""
    window = int(window)
    r = _client()
    if r is not None:
        try:
            k = f"rl:{key}:{int(time.time()) // window}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window * 2)
            return n <= limit
        except Exception:
            pass
    now = time.monotonic()
    if len(_local_hits) > 100000:
        _local_hits.clear()
    start, n = _local_hits.get(key, (now, 0))
    if now - start >= window:
        start, n = now, 0
    _local_hits[key] = (start, n + 1)
    return n + 1 <= limit
