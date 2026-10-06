import time
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import abort, current_app, request, session
from flask_login import current_user


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return abort(401)
        if not current_user.is_admin:
            return abort(403)
        return view(*args, **kwargs)

    return wrapped


def is_safe_redirect(target):
    """Only allow same-site relative redirects after login."""
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def start_login_clock():
    """Call right after login_user(): marks the session permanent and records when it began."""
    session.permanent = True
    session["_login_at"] = int(time.time())


def session_seconds_left():
    """Seconds until the current login expires (None if there is no login clock yet)."""
    started = session.get("_login_at")
    if started is None:
        return None
    return int(started) + current_app.config["SESSION_LIFETIME_SECONDS"] - int(time.time())
