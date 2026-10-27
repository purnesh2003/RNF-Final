"""Publish-later: parse the admin's chosen time, and announce posts/quizzes when their time arrives.

A scheduled post or quiz is stored right away with created_at = the publish time. Every page only lists
items whose created_at has passed, so it simply "appears" on time. A small background thread then e-mails
members once (claimed atomically through notified_at, so several workers can never send it twice).
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import current_app

from .extensions import db
from .models import Post, Quiz, utcnow

TICK_SECONDS = 30
MAX_AHEAD_DAYS = 365


def schedule_tz():
    name = current_app.config.get("SCHEDULE_TZ") or "Asia/Kolkata"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # no tz database on this machine: India time has no daylight saving, so a fixed offset is exact
        return timezone(timedelta(hours=5, minutes=30))


def parse_publish_at(raw):
    """Admin form value (datetime-local, in SCHEDULE_TZ) -> (utc datetime or None, error). Blank = publish now."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    try:
        local = datetime.fromisoformat(raw)
    except ValueError:
        return None, "Please choose a valid date and time to publish."
    when = (local.replace(tzinfo=schedule_tz()) if local.tzinfo is None else local).astimezone(timezone.utc)
    now = utcnow()
    if when < now + timedelta(minutes=1):
        return None, "The publish time must be in the future."
    if when > now + timedelta(days=MAX_AHEAD_DAYS):
        return None, "The publish time can be at most one year ahead."
    return when, None


def to_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(schedule_tz())


def publish_due():
    """Announce every scheduled post/quiz whose time has come. Safe to call at any moment, from any worker."""
    from . import notify, quiz_notify

    now = utcnow()
    done = 0
    for pid, in db.session.query(Post.id).filter(Post.publish_at.isnot(None), Post.notified_at.is_(None),
                                                  Post.created_at <= now).all():
        claimed = Post.query.filter_by(id=pid, notified_at=None).update({"notified_at": now})
        db.session.commit()
        if claimed:
            notify.announce_post(db.session.get(Post, pid))
            done += 1
    for qid, in db.session.query(Quiz.id).filter(Quiz.publish_at.isnot(None), Quiz.notified_at.is_(None),
                                                  Quiz.created_at <= now).all():
        if quiz_notify.announce_quiz(qid):
            done += 1
    return done


def start(app):
    """Background loop for the running site (not used by tests or CLI commands)."""
    if app.config.get("TESTING") or not app.config.get("SCHEDULER_ENABLED", True):
        return

    def loop():
        while True:
            time.sleep(TICK_SECONDS)
            try:
                with app.app_context():
                    publish_due()
                    db.session.remove()
            except Exception:
                logging.exception("scheduled publishing failed")

    threading.Thread(target=loop, daemon=True, name="scheduler").start()
