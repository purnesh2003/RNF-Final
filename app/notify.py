"""Shared helpers for "tell the members" e-mails (quiz announcements, admin posts)."""
import threading
from html import escape

from flask import current_app

from . import mailer
from .extensions import db
from .models import User


def members(exclude_ids=()):
    """[(name, email)] of every active member, optionally leaving some people out (e.g. the author)."""
    q = db.session.query(User.name, User.email).filter_by(active=True, email_verified=True)
    if exclude_ids:
        q = q.filter(~User.id.in_(list(exclude_ids)))
    return [(n, e) for n, e in q.order_by(User.id).all() if e]


def deliver(subject, text, html, recipients):
    """One personal e-mail per member ("Hi <first name>,", and the member is the only one in To).
    text/html contain the token @@NAME@@ where the first name goes."""
    def items():
        for name, email in recipients:
            first = (name or "").strip().split(" ")[0] or "there"
            yield email, subject, text.replace("@@NAME@@", first), html.replace("@@NAME@@", escape(first))
    sent = mailer.send_each(items())
    current_app.logger.info("Member e-mail \"%s\" sent to %s of %s members", subject, sent, len(recipients))
    return sent


def in_background(fn):
    """Run fn() inside an app context on a thread (straight away, in the same thread, while testing)."""
    app = current_app._get_current_object()
    if app.testing:
        return fn()

    def work():
        with app.app_context():
            try:
                fn()
            except Exception:
                app.logger.exception("Background e-mail job failed")
    threading.Thread(target=work, daemon=True).start()


# ------------------------------------------------------------ admin posts / community messages
def _enabled():
    return bool(current_app.config.get("ADMIN_POST_EMAILS", True) and mailer.mail_configured())


def _snippet(body, n=300):
    body = " ".join((body or "").split())
    return body if len(body) <= n else body[:n].rsplit(" ", 1)[0] + "..."


def _short(text, n=70):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0].rstrip(",.;:- ") + "..."


def _compose(kind, title, body, file_name, link, where):
    site = current_app.config["SITE_NAME"]
    what = f"posted {kind} in {where}"
    text = (f"Hi @@NAME@@,\n\nThe admin {what} on {site}.\n\n"
            + (f"{title}\n" if title else "") + (f"{_snippet(body)}\n" if body else "")
            + (f"File: {file_name}\n" if file_name else "")
            + f"\nOpen it here:\n{link}\n\nYou are receiving this because you are a member of the community.")
    html = (f"<p>Hi @@NAME@@,</p><p>The admin {escape(what)} on <strong>{escape(site)}</strong>.</p>"
            + (f"<p><strong>{escape(title)}</strong></p>" if title else "")
            + (f"<p>{escape(_snippet(body))}</p>" if body else "")
            + (f"<p>&#128206; {escape(file_name)}</p>" if file_name else "")
            + f'<p><a href="{escape(link)}">Open it</a></p>'
            '<p style="color:#6b7280;font-size:12px">You are receiving this because you are a member of the community.</p>')
    return text, html


def announce_post(post):
    """Admin published a feed post (with or without a file): e-mail the other active members. Never raises."""
    try:
        if not _enabled():
            return False
        from .main import SECTION_ENDPOINTS
        recipients = members(exclude_ids=[post.author_id])
        if not recipients:
            return False
        where = post.SECTIONS.get(post.section, "the feed").split(" ", 1)[-1]
        link = mailer.external_link(SECTION_ENDPOINTS.get(post.section, "main.home"))
        text, html = _compose("a file" if post.file_key and not post.body else "an update",
                              post.title, post.body, post.file_name, link, where)
        subject = "New from the admin: " + _short(post.title)
        in_background(lambda: deliver(subject, text, html, recipients))
        return True
    except Exception:
        current_app.logger.exception("Could not start the post e-mail")
        return False


def announce_message(msg, author):
    """Admin wrote a community message or shared a file there: e-mail the other active members. Never raises."""
    try:
        if not author or not author.is_admin or not _enabled():
            return False
        recipients = members(exclude_ids=[author.id])
        if not recipients:
            return False
        from .models import Message
        room = Message.CHANNELS.get(msg.channel, "General") + " chat"
        link = mailer.external_link("community.chat") + f"#{msg.channel}"
        text, html = _compose("a file" if msg.file_key else "a message", "", msg.body, msg.file_name, link, room)
        subject = "New in the community: " + _short(msg.body or msg.file_name or "a file")
        in_background(lambda: deliver(subject, text, html, recipients))
        return True
    except Exception:
        current_app.logger.exception("Could not start the community e-mail")
        return False
