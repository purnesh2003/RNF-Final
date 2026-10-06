from datetime import date, datetime, timezone
from html import escape

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError

from .extensions import db, limiter
from .mailer import external_link, send_mail
from .models import User
from .utils import is_safe_redirect, start_login_clock
from .validators import check_email, check_password

bp = Blueprint("auth", __name__)


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _send_reset_email(user, token):
    """E-mail the reset link. Returns (sent, dev_link): dev_link is only set when mail could not be sent
    and DEV_SHOW_RESET_LINK is on (local testing), so the flow can still be tried without an inbox."""
    link = external_link("auth.reset_password", token=token)
    minutes = current_app.config["PASSWORD_RESET_TTL"] // 60
    site = current_app.config["SITE_NAME"]
    text = (
        f"Hi {user.name},\n\n"
        f"Use this link to reset your {site} password:\n{link}\n\n"
        f"This link expires in {minutes} minutes. If you did not request this, you can ignore this email.\n"
    )
    html = (
        f"<p>Hi {escape(user.name)},</p>"
        f"<p>Use the button below to reset your {escape(site)} password:</p>"
        f"<p><a href=\"{escape(link, quote=True)}\">Reset password</a></p>"
        f"<p>This link expires in {minutes} minutes. If you did not request this, you can ignore this email.</p>"
    )
    sent = send_mail(user.email, f"Reset your {site} password", text, html)
    dev_link = link if (not sent and current_app.config["DEV_SHOW_RESET_LINK"]) else None
    return sent, dev_link


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email, email_err = check_email(request.form.get("email", ""))
        dob_raw = request.form.get("dob", "").strip()
        occupation = " ".join(request.form.get("occupation", "").split())[:100]
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        error, dob = None, None
        try:
            dob = date.fromisoformat(dob_raw)
        except ValueError:
            pass
        if not name:
            error = "Please enter your name."
        elif email_err:
            error = email_err
        elif dob is None or dob > date.today() or dob.year < 1900:
            error = "Please enter a valid date of birth."
        elif not occupation:
            error = "Please enter your occupation."
        elif check_password(pw):
            error = check_password(pw)
        elif pw != pw2:
            error = "Passwords do not match."
        elif User.query.filter_by(email=email).first():
            error = "An account with this email already exists."
        if error:
            flash(error, "danger")
            return render_template("register.html", name=name, email=email, dob=dob_raw, occupation=occupation, today=date.today().isoformat()), 400
        user = User(name=name, email=email, dob=dob, occupation=occupation)
        user.set_password(pw)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:  # two sign-ups with the same email at the same moment
            db.session.rollback()
            flash("An account with this email already exists.", "danger")
            return render_template("register.html", name=name, email=email, dob=dob_raw, occupation=occupation, today=date.today().isoformat()), 400
        login_user(user)
        start_login_clock()
        flash("Welcome to the community!", "success")
        return redirect(url_for("main.home"))
    return render_template("register.html", today=date.today().isoformat())


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if request.method == "GET" and request.args.get("expired"):
        flash("Your session expired. Please log in again.", "info")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            if not user.active:
                flash("This account has been suspended. Contact the admin.", "danger")
                return render_template("login.html", email=email), 403
            login_user(user)  # no "remember me": every login lasts exactly SESSION_LIFETIME_SECONDS
            from flask import session
            session["_auth_version"] = user.session_version
            start_login_clock()
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            nxt = request.args.get("next")
            return redirect(nxt if is_safe_redirect(nxt) else url_for("main.home"))
        flash("Wrong email or password.", "danger")
        return render_template("login.html", email=email), 401
    return render_template("login.html")


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:255]
        user = User.query.filter_by(email=email).first() if email else None
        # Always return the same user-facing result so the endpoint cannot be used
        # to enumerate registered email addresses.
        dev_link = None
        if user and user.active:
            payload = {"uid": user.id, "sv": user.session_version}
            token = _reset_serializer().dumps(payload)
            _, dev_link = _send_reset_email(user, token)
        flash("If an active account exists for that email, a password reset link has been sent. Check your inbox and spam folder.", "info")
        if dev_link:
            # Local testing only (mail not set up): never shown in production.
            flash(f"Development reset link: {dev_link}", "warning")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    try:
        data = _reset_serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_TTL"])
        user = db.session.get(User, int(data["uid"]))
        if not user or not user.active or int(data.get("sv", -1)) != user.session_version:
            raise BadSignature()
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        flash("That password reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new, new2 = request.form.get("password", ""), request.form.get("confirm", "")
        if check_password(new):
            flash(check_password(new), "danger")
        elif new != new2:
            flash("Passwords do not match.", "danger")
        else:
            user.set_password(new)
            user.must_change_password = False
            user.session_version += 1
            db.session.commit()
            login_user(user)
            from flask import session
            session["_auth_version"] = user.session_version
            start_login_clock()
            flash("Your password has been reset successfully.", "success")
            return redirect(url_for("main.home"))
    return render_template("reset_password.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.home"))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"])
def change_password():
    if request.method == "POST":
        cur, new, new2 = (request.form.get(k, "") for k in ("current", "password", "confirm"))
        if not current_user.check_password(cur):
            flash("Current password is wrong.", "danger")
        elif check_password(new):
            flash(check_password(new), "danger")
        elif new != new2:
            flash("New passwords do not match.", "danger")
        elif new == cur:
            flash("Choose a different password.", "danger")
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            current_user.session_version += 1
            db.session.commit()
            login_user(current_user)
            from flask import session
            session["_auth_version"] = current_user.session_version
            flash("Password updated.", "success")
            return redirect(url_for("main.home"))
    return render_template("change_password.html")
