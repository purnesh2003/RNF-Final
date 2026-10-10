"""Sign-up input rules: real-looking e-mail addresses and strong passwords."""
import re

from flask import current_app

MIN_PASSWORD = 12

# Sign-up accepts Gmail addresses by default. Add company / college domains with
# EMAIL_ALLOWED_DOMAINS="gmail.com,acharya.ac.in", or set EMAIL_ALLOWED_DOMAINS="*" to accept any real-looking domain.
DEFAULT_ALLOWED_DOMAINS = ("gmail.com", "googlemail.com")  # Gmail only; the mailbox is then proven by the e-mailed confirmation link
# Throw-away inboxes; only checked when the allow-list is switched off ("*").
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org", "yopmail.com",
    "trashmail.com", "sharklasers.com", "getnada.com", "throwawaymail.com", "dispostable.com", "maildrop.cc",
    "fakeinbox.com", "mailnesia.com", "mintemail.com", "mohmal.com", "tempail.com", "emailondeck.com",
}
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@((?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})$")


def allowed_domains():
    raw = current_app.config.get("EMAIL_ALLOWED_DOMAINS", "") or ""
    items = [d.strip().lower() for d in raw.split(",") if d.strip()]
    return set(items) if items else set(DEFAULT_ALLOWED_DOMAINS)


def check_email(raw):
    """Return (clean_email, error). error is None when the address is acceptable."""
    email = (raw or "").strip().lower()
    if len(email) > 254:
        return email, "Please enter a valid email address."
    m = _EMAIL_RE.match(email)
    local = email.split("@")[0] if m else ""
    if not m or local.startswith(".") or local.endswith(".") or ".." in local:
        return email, "Please enter a valid email address, like name@gmail.com."
    domain = m.group(1)
    allowed = allowed_domains()
    if "*" in allowed:
        if domain in DISPOSABLE_DOMAINS:
            return email, "Temporary email addresses are not allowed. Please use your real email."
    elif domain not in allowed:
        return email, "Please use a real email from a trusted provider, like name@gmail.com."
    if domain in ("gmail.com", "googlemail.com"):  # Gmail's own username rules weed out most made-up addresses
        base = local.split("+")[0]
        if not re.fullmatch(r"[a-z0-9.]+", base) or not 6 <= len(base.replace(".", "")) <= 30:
            return email, "That doesn't look like a real Gmail address (Gmail names have 6–30 letters or numbers)."
    return email, None


def check_password(pw):
    """Return an error message, or None if the password is strong enough."""
    max_len = current_app.config["MAX_PASSWORD_LENGTH"]
    if len(pw) < MIN_PASSWORD or len(pw) > max_len:
        return f"Password must be {MIN_PASSWORD}–{max_len} characters long."
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw)):
        return "Password must include a letter, a number and a special character (for example @ # ! $ %)."
    return None


PASSWORD_PATTERN = r"(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,128}"
PASSWORD_HINT = "At least 12 characters with a letter, a number and a special character (@ # ! $ %)."
