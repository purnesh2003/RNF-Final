"""Community chat: REST for history + uploads, Socket.IO for live messages."""
from types import SimpleNamespace

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from flask_socketio import disconnect, emit, join_room
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import chatmode, metrics, storage, throttle
from .extensions import db, limiter, socketio
from .utils import session_seconds_left
from .models import Message, User

bp = Blueprint("community", __name__)
ROOM = "community"

def _too_fast(user_id):
    """Flood guard: 10 messages per 10 s per user, shared across servers via Redis."""
    return not throttle.within_limit(f"flood:{user_id}", 10, 10)


def _blocked(user, consume=True):
    """Why this member cannot post right now (a message for them), or None if they can.
    consume=False checks the rules without starting the slow-mode cooldown."""
    if user.muted:
        return "You are muted by the admin."
    if user.is_admin:
        return None
    mode = chatmode.get_mode()
    if mode == "admins":
        return "Chat is in announcement mode - only the admin can post right now."
    if mode == "slow" and consume:
        secs = current_app.config["CHAT_SLOW_SECONDS"]
        if not throttle.allow(f"slow:{user.id}", secs):
            return f"Slow mode is on - you can post once every {secs} seconds."
    return None


def _signer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="direct-upload")


def _channel(raw):
    """Only the known channel keys are accepted; anything else falls back to General."""
    return raw if raw in Message.CHANNELS else Message.DEFAULT_CHANNEL


def _publish(msg):
    db.session.add(msg)
    db.session.commit()
    socketio.emit("message", msg.to_dict(), to=ROOM)
    from . import notify  # admin messages/files are also e-mailed to the members
    notify.announce_message(msg, db.session.get(User, msg.user_id))


@bp.route("/community")
@login_required
def chat():
    return render_template("community.html", chat_mode=chatmode.get_mode(), channels=Message.CHANNELS)


@bp.route("/community/history")
@login_required
def history():
    before = request.args.get("before", type=int)
    after = request.args.get("after", type=int)
    q = Message.query.filter_by(deleted=False, channel=_channel(request.args.get("channel")))
    if before:
        q = q.filter(Message.id < before).order_by(Message.id.desc())
    elif after:
        q = q.filter(Message.id > after).order_by(Message.id.asc())
    else:
        q = q.order_by(Message.id.desc())
    rows = q.limit(current_app.config["CHAT_HISTORY_PAGE"]).all()
    if not after:  # newest-first queries are flipped so the page reads oldest to newest; "after" is already oldest-first
        rows = list(reversed(rows))
    return jsonify([m.to_dict() for m in rows])


# ------------------------------------------------------------- uploads
@bp.route("/community/upload-url", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def upload_url():
    """Step 1 of a file upload. On AWS (S3) the browser sends the file straight to S3 using the
    one-time form returned here; locally it is told to use the plain server upload instead."""
    err = _blocked(current_user, consume=False)
    if err:
        return jsonify(ok=False, error=err), 403
    data = request.get_json(silent=True) or {}
    name, size = str(data.get("filename", "")), data.get("size")

    ok, verr, ext = storage.validate(SimpleNamespace(filename=name))
    if not ok:
        return jsonify(ok=False, error=verr), 400
    too_big = storage.size_error(ext, size)
    if too_big:
        return jsonify(ok=False, error=too_big), 400
    if not current_app.config["S3_BUCKET"]:
        return jsonify(ok=True, mode="server")
    form, meta = storage.presign_upload(name, ext)
    token = _signer().dumps({**meta, "u": current_user.id})
    return jsonify(ok=True, mode="s3", url=form["url"], fields=form["fields"], token=token)


@bp.route("/community/upload-complete", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def upload_complete():
    """Step 2 (S3 mode): the file is already in S3; verify the receipt and post the chat message."""
    err = _blocked(current_user)
    if err:
        return jsonify(ok=False, error=err), 403
    data = request.get_json(silent=True) or {}
    try:
        meta = _signer().loads(str(data.get("token", "")), max_age=current_app.config["UPLOAD_TOKEN_MAX_AGE"])
    except SignatureExpired:
        return jsonify(ok=False, error="Upload took too long - please try again."), 400
    except BadSignature:
        return jsonify(ok=False, error="Invalid upload receipt."), 400
    if meta.get("u") != current_user.id:
        return jsonify(ok=False, error="Invalid upload receipt."), 403
    if not storage.object_ok(meta["key"], storage.limit_bytes(meta["key"].rsplit(".", 1)[-1])):
        return jsonify(ok=False, error="The uploaded file failed storage validation. Please try again."), 400
    if Message.query.filter_by(file_key=meta["key"]).first():
        return jsonify(ok=False, error="This upload was already posted."), 409
    _publish(Message(
        user_id=current_user.id,
        body=str(data.get("caption", "")).strip()[: current_app.config["MAX_MESSAGE_LEN"]],
        file_key=meta["key"], file_name=meta["name"], file_mime=meta["mime"],
        channel=_channel(data.get("channel")),
    ))
    return jsonify(ok=True)


@bp.route("/community/upload", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def upload():
    """Plain server-side upload (used locally, or if S3 is not configured)."""
    err = _blocked(current_user)
    if err:
        return jsonify(ok=False, error=err), 403
    file = request.files.get("file")
    ok, verr, ext = storage.validate(file)
    if not ok:
        return jsonify(ok=False, error=verr), 400
    too_big = storage.size_error(ext, storage.stream_size(file))
    if too_big:
        return jsonify(ok=False, error=too_big), 400
    saved = storage.save_upload(file, ext)
    _publish(Message(
        user_id=current_user.id,
        body=request.form.get("caption", "").strip()[: current_app.config["MAX_MESSAGE_LEN"]],
        file_key=saved["key"], file_name=saved["name"], file_mime=saved["mime"],
        channel=_channel(request.form.get("channel")),
    ))
    return jsonify(ok=True)


# ---------------------------------------------------------------- Socket.IO
@socketio.on("connect")
def on_connect():
    if not current_user.is_authenticated:
        return False  # reject anonymous sockets
    left = session_seconds_left()
    if left is not None and left <= 0:
        return False  # login hour is over
    join_room(ROOM)
    metrics.connected(request.sid)
    emit("chat_mode", {"mode": chatmode.get_mode()})


@socketio.on("disconnect")
def on_disconnect():
    metrics.disconnected(request.sid)


@socketio.on("send_message")
def on_send_message(data):
    if not current_user.is_authenticated:
        return {"ok": False, "error": "Please log in."}
    left = session_seconds_left()  # a socket opened earlier must not outlive the login hour
    if left is not None and left <= 0:
        disconnect()
        return {"ok": False, "error": "Your session expired. Please log in again."}
    body = ((data or {}).get("body") or "").strip()
    if not body:
        return {"ok": False, "error": "Message is empty."}
    err = _blocked(current_user)
    if err:
        return {"ok": False, "error": err}
    if _too_fast(current_user.id):
        return {"ok": False, "error": "Slow down a little."}
    _publish(Message(user_id=current_user.id, body=body[: current_app.config["MAX_MESSAGE_LEN"]],
                     channel=_channel((data or {}).get("channel"))))
    return {"ok": True}
