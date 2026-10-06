"""Outgoing e-mail: Gmail/any SMTP server (works locally and on AWS), or Amazon SES as a fallback."""
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from flask import current_app, url_for


def _sender():
    cfg = current_app.config
    raw = cfg.get("MAIL_FROM") or cfg.get("SMTP_USER") or cfg.get("PASSWORD_RESET_EMAIL_FROM") or ""
    name, addr = parseaddr(raw)
    return formataddr((name or cfg["SITE_NAME"], addr)) if addr else ""


def mail_configured():
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and _sender()) or bool(cfg.get("PASSWORD_RESET_EMAIL_FROM"))


def external_link(endpoint, **values):
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if base:
        return base + url_for(endpoint, **values)
    return url_for(endpoint, _external=True, **values)


def send_mail(to, subject, text, html=None, bcc=None):
    """Send one message (optionally with hidden BCC recipients). Returns True on success, False (and logs why) on failure; never raises."""
    cfg = current_app.config
    try:
        if cfg.get("SMTP_HOST"):
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, _sender(), to
            if bcc:
                msg["Bcc"] = ", ".join(bcc)  # send_message() delivers to Bcc but strips the header
            msg.set_content(text)
            if html:
                msg.add_alternative(html, subtype="html")
            port = int(cfg.get("SMTP_PORT") or 587)
            if cfg.get("SMTP_USE_SSL"):
                server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, timeout=15)
            else:
                server = smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=15)
            with server:
                if not cfg.get("SMTP_USE_SSL"):
                    server.starttls()
                if cfg.get("SMTP_USER"):
                    server.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD", ""))
                server.send_message(msg)
            return True
        if cfg.get("PASSWORD_RESET_EMAIL_FROM"):  # Amazon SES through the ECS task role
            import boto3

            body = {"Text": {"Data": text, "Charset": "UTF-8"}}
            if html:
                body["Html"] = {"Data": html, "Charset": "UTF-8"}
            boto3.client("ses", region_name=cfg["AWS_REGION"]).send_email(
                Source=_sender(), Destination={"ToAddresses": [to], **({"BccAddresses": list(bcc)} if bcc else {})},
                Message={"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body})
            return True
        current_app.logger.warning("Mail is not configured (set SMTP_HOST/SMTP_USER/SMTP_PASSWORD); nothing sent to %s", to)
    except Exception:  # network, auth, SES sandbox... the caller decides what to tell the member
        current_app.logger.exception("Sending e-mail failed")
    return False


def _smtp_connect():
    cfg = current_app.config
    port = int(cfg.get("SMTP_PORT") or 587)
    if cfg.get("SMTP_USE_SSL"):
        server = smtplib.SMTP_SSL(cfg["SMTP_HOST"], port, timeout=30)
    else:
        server = smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=30)
        server.starttls()
    if cfg.get("SMTP_USER"):
        server.login(cfg["SMTP_USER"], cfg.get("SMTP_PASSWORD", ""))
    return server


def _build(to, subject, text, html):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, _sender(), to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send_each(items, reconnect_every=100):
    """Send many personal messages (each one addressed only to its own recipient).
    items: iterable of (to, subject, text, html). Re-uses one SMTP login for many messages instead of
    logging in every time. Returns how many were sent; never raises; one bad address does not stop the rest."""
    cfg = current_app.config
    if not cfg.get("SMTP_HOST"):
        return sum(1 for to, subject, text, html in items if send_mail(to, subject, text, html))
    sent, server, since = 0, None, 0
    try:
        for to, subject, text, html in items:
            for attempt in (1, 2):
                try:
                    if server is None or since >= reconnect_every:
                        if server is not None:
                            try:
                                server.quit()
                            except Exception:
                                pass
                        server, since = _smtp_connect(), 0
                    server.send_message(_build(to, subject, text, html))
                    sent += 1
                    since += 1
                    break
                except smtplib.SMTPRecipientsRefused:
                    current_app.logger.warning("Mail to one member was refused (bad address)")
                    break
                except Exception:
                    current_app.logger.exception("Sending e-mail failed (attempt %s)", attempt)
                    server = None  # reconnect and try this one message again, once
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
    return sent
