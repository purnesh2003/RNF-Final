import os
import secrets

import click
from flask import Flask, g, jsonify, session, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .validators import PASSWORD_HINT, PASSWORD_PATTERN
from .utils import session_seconds_left, start_login_clock
from .extensions import csrf, db, limiter, login_manager, migrate, socketio


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config["APP_ENV"] == "production" and app.config["SECRET_KEY"].startswith("dev-only"):
        raise RuntimeError("Set a strong SECRET_KEY in production.")

    if app.config["TRUST_PROXY"]:  # behind ALB / CloudFront: trust X-Forwarded-*
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Import blueprints FIRST: importing community.py registers the Socket.IO event
    # handlers, and they must exist before socketio.init_app() wires up the server.
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .community import bp as community_bp
    from .main import bp as main_bp

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"
    socketio.init_app(
        app,
        message_queue=app.config["REDIS_URL"] or None,  # lets many servers share one chat
        cors_allowed_origins=[o.strip() for o in app.config["CORS_ORIGINS"].split(",") if o.strip()] or None,
        async_mode=app.config["SOCKETIO_ASYNC_MODE"],
        max_http_buffer_size=app.config["SOCKET_MAX_BUFFER"],  # drop oversized chat packets early
        ping_interval=25,
        ping_timeout=30,
    )
    from . import chatmode

    chatmode.reset_cache()

    for bp in (main_bp, auth_bp, community_bp, admin_bp):
        app.register_blueprint(bp)

    @app.before_request
    def enforce_session_timeout():
        """Log members out once their hour is up (works for pages, fetch calls and the chat socket)."""
        if not current_user.is_authenticated or request.endpoint in ("static", "main.healthz", "main.readyz"):
            return None
        left = session_seconds_left()
        if left is None:  # session created before this feature: start its clock now
            start_login_clock()
            return None
        if left <= 0:
            logout_user()
            session.clear()
            if request.headers.get("X-Requested-With") == "fetch" or request.is_json:
                return jsonify(ok=False, error="Your session expired. Please log in again."), 401
            return redirect(url_for("auth.login", expired=1))
        return None

    @app.before_request
    def force_password_change():
        if (
            current_user.is_authenticated
            and current_user.must_change_password
            and request.endpoint
            and request.endpoint not in ("auth.change_password", "auth.logout", "static", "main.healthz")
        ):
            return redirect(url_for("auth.change_password"))

    @app.before_request
    def make_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        nonce = getattr(g, "csp_nonce", "")
        s3 = f" https://{app.config['S3_BUCKET']}.s3.{app.config['AWS_REGION']}.amazonaws.com" if app.config["S3_BUCKET"] else ""
        resp.headers.setdefault("Content-Security-Policy", (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "script-src-attr 'none'; "
            "style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: blob:{s3}; font-src 'self' data:; "
            f"connect-src 'self' ws://{request.host} wss://{request.host}{s3}; media-src 'self' blob:{s3}"
        ))
        if app.config["APP_ENV"] == "production":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    @app.template_filter("timeago")
    def timeago(dt):
        from datetime import datetime, timezone
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        if secs < 7 * 86400:
            return f"{secs // 86400}d"
        return dt.strftime("%d %b %Y")

    @app.context_processor
    def inject_globals():
        return {
            "site_name": app.config["SITE_NAME"],
            "now_year": __import__("datetime").date.today().year,
            "wa_link": app.config["WHATSAPP_COMMUNITY_LINK"],
            "csp_nonce": getattr(g, "csp_nonce", ""),
            "pw_pattern": PASSWORD_PATTERN,
            "pw_hint": PASSWORD_HINT,
            "session_left": session_seconds_left() if current_user.is_authenticated else None,
        }

    for code, msg in ((401, "Please log in."), (403, "You don't have access to this page."),
                      (404, "Page not found."), (413, "That file is too large.")):
        app.register_error_handler(
            code, lambda e, code=code, msg=msg: (render_template("error.html", code=code, msg=msg), code)
        )

    register_cli(app)
    return app


def register_cli(app):
    from .models import User

    def _make_admin(email, password, name="Admin"):
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            user.role = "admin"
            user.active = True
        else:
            user = User(name=name, email=email, role="admin")
            user.set_password(password)
            user.must_change_password = os.environ.get("ADMIN_FORCE_CHANGE", "0") == "1"
            db.session.add(user)
        db.session.commit()
        return user

    @app.cli.command("init-db")
    def init_db():
        """Development-only bootstrap. Production uses `flask db upgrade` for schema changes."""
        from sqlalchemy import inspect
        if not inspect(db.engine).has_table("users"):
            db.create_all()
            click.echo("Created initial database tables.")
        else:
            click.echo("Database tables already exist; use `flask db upgrade` for migrations.")
        click.echo("Database ready.")

    @app.cli.command("ensure-admin")
    def ensure_admin():
        """Create the configured bootstrap admin if it does not already exist."""
        email, pw = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
        if not email or not pw:
            raise click.ClickException("ADMIN_EMAIL and ADMIN_PASSWORD must be configured.")
        user = User.query.filter_by(email=email.strip().lower()).first()
        if user:
            click.echo(f"Admin already exists: {email.strip().lower()}")
            return
        _make_admin(email, pw, os.environ.get("ADMIN_NAME", "Rakshith N"))
        click.echo(f"Admin created: {email.strip().lower()}")

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.password_option()
    def create_admin(email, password):
        """Create (or promote) an admin account."""
        _make_admin(email, password)
        click.echo(f"Admin ready: {email}")
