"""Admin-controlled chat mode: open | slow | admins (announcement-only).

The mode lives in the database; each server caches it for a few seconds so chat messages
don't cost a database read.
"""
import time

from .extensions import db
from .models import Setting

MODES = ("open", "slow", "admins")
_TTL = 5.0
_cache = {"v": "open", "t": -1e9}


def reset_cache():
    _cache.update(v="open", t=-1e9)


def get_mode():
    now = time.monotonic()
    if now - _cache["t"] > _TTL:
        row = db.session.get(Setting, "chat_mode")
        _cache.update(v=row.value if row and row.value in MODES else "open", t=now)
    return _cache["v"]


def set_mode(mode):
    if mode not in MODES:
        raise ValueError("bad chat mode")
    row = db.session.get(Setting, "chat_mode")
    if row:
        row.value = mode
    else:
        db.session.add(Setting(key="chat_mode", value=mode))
    db.session.commit()
    _cache.update(v=mode, t=time.monotonic())
