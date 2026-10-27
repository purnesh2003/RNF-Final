"""Pre-market and post-market updates, written by hand by the admin (no AI, no API cost).

The admin writes each update on Admin > Market updates; the two buttons in the community chat show the latest
saved one. Members only read the saved row, so any number of clicks costs nothing.
"""
import re
from datetime import date

from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import MarketUpdate, utcnow

KINDS = {"pre": "Pre-market update", "post": "Post-market update"}
MAX_BODY, MIN_BODY = 5000, 20


def clean_body(value):
    """Plain text with line breaks kept: no HTML, no control characters, no markdown emphasis, bounded length."""
    if not isinstance(value, str):
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"\*\*|__|`|^#+\s*", "", value, flags=re.M)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()[:MAX_BODY]


def today_local():
    from .scheduler import to_local
    return to_local(utcnow()).date()


def latest(kind):
    return MarketUpdate.query.filter_by(kind=kind).order_by(MarketUpdate.for_date.desc(), MarketUpdate.id.desc()).first()


def save(kind, for_date, body):
    """Create the update for this day, or replace the one already there. Returns (row, error, replaced)."""
    if kind not in KINDS:
        return None, "Choose pre-market or post-market.", False
    if not isinstance(for_date, date):
        return None, "Choose a valid date.", False
    body = clean_body(body)
    if len(body) < MIN_BODY:
        return None, "Write the update text (at least a couple of lines).", False
    row = MarketUpdate.query.filter_by(kind=kind, for_date=for_date).first()
    replaced = row is not None
    if row:
        row.body, row.created_at = body, utcnow()
    else:
        row = MarketUpdate(kind=kind, for_date=for_date, body=body, sources=[])
        db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:  # two saves for the same day at the same moment: keep the later text
        db.session.rollback()
        row = MarketUpdate.query.filter_by(kind=kind, for_date=for_date).first()
        row.body, row.created_at = body, utcnow()
        db.session.commit()
        replaced = True
    return row, None, replaced
