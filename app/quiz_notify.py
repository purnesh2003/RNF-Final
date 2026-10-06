"""E-mail every active member when a new quiz is published (once per quiz, never blocks the admin)."""
from datetime import datetime, timezone

from flask import current_app

from .extensions import db
from .mailer import external_link, mail_configured
from .notify import deliver, in_background, members
from .models import Quiz

MAX_SUBJECT = 70


def _compose(quiz, link):
    kind = f" ({quiz.difficulty.capitalize()})" if quiz.difficulty else ""
    n = len(quiz.questions)
    title = " ".join((quiz.title or "").split())
    short = title if len(title) <= MAX_SUBJECT else title[:MAX_SUBJECT].rsplit(" ", 1)[0].rstrip(",.;:- ") + "..."
    subject = f"New quiz: {short}"
    text = (f"Hi @@NAME@@,\n\nA new quiz is live on {current_app.config['SITE_NAME']}.\n\n"
            f"{quiz.title}{kind} - {n} question{'s' if n != 1 else ''}\n"
            f"{(quiz.description or '').strip()}\n\n"
            f"Take it here (you can attempt it once):\n{link}\n\n"
            "You are receiving this because you are a member of the community.")
    from html import escape
    html = (f"<p>Hi @@NAME@@,</p><p>A new quiz is live on <strong>{escape(current_app.config['SITE_NAME'])}</strong>.</p>"
            f"<p><strong>{escape(quiz.title)}</strong>{escape(kind)} &ndash; {n} question{'s' if n != 1 else ''}</p>"
            + (f"<p>{escape(quiz.description.strip())}</p>" if (quiz.description or '').strip() else "")
            + f'<p><a href="{escape(link)}">Take the quiz</a> (you can attempt it once).</p>'
            "<p style=\"color:#6b7280;font-size:12px\">You are receiving this because you are a member of the community.</p>")
    return subject, text, html


def announce_quiz(quiz_id):
    """Claim the quiz (notified_at) so it can never be announced twice, then mail members in the
    background. Returns True if a mail-out was started. Safe to call when mail is not configured."""
    app = current_app._get_current_object()
    if not app.config.get("QUIZ_NOTIFY_EMAILS", True) or not mail_configured():
        return False
    quiz = db.session.get(Quiz, quiz_id)
    if quiz is None or quiz.notified_at is not None:
        return False
    claimed = Quiz.query.filter_by(id=quiz_id, notified_at=None).update(
        {"notified_at": datetime.now(timezone.utc)})
    db.session.commit()
    if not claimed:  # another request got there first
        return False
    recipients = members()
    if not recipients:
        return False
    subject, text, html = _compose(quiz, external_link("main.take_quiz", quiz_id=quiz.id))
    in_background(lambda: deliver(subject, text, html, recipients))
    return True
