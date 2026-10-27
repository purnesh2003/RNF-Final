"""Numbers for the admin Analytics page (members, activity, occupations, quiz attendance, chat).

Everything is read-only and computed on request from data the site already stores:
  * who signed up and when  (users.created_at, occupation, dob)
  * when members were last here (users.last_login - set at every login; sessions last one hour)
  * quiz attempts, chat messages
Admin accounts are left out of the member numbers.
"""
import re
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from . import metrics
from .extensions import db
from .models import Message, Quiz, QuizAttempt, User, quiz_is_live

RANGES = (7, 30, 90)
DEFAULT_RANGE = 30

# Occupation is typed freely at sign-up ("Student", "software engineer", "CA"...), so similar answers are
# grouped. First match wins, so "engineering student" counts as a Student. Anything else is "Other".
OCCUPATION_GROUPS = [
    ("Student", r"student|studying|pursuing|undergrad|\bschool\b|\bcollege\b|\bb\.?\s?tech\b|\bmba\b|\bintern\b|\bscholar"),
    ("Engineer", r"engineer|developer|programmer|software|\bit\b|\btech\b|devops|architect"),
    ("Teacher / Professor", r"teacher|professor|lecturer|tutor|faculty|educator|\bteaching\b"),
    ("Doctor / Healthcare", r"doctor|\bdr\b|nurse|medical|pharma|dentist|health"),
    ("Finance / Accounting", r"account|\bca\b|banker|bank|finance|financial|analyst|trader|investor|advisor|insurance|auditor|broker"),
    ("Business / Self-employed", r"business|self.?employed|entrepreneur|owner|freelanc|shop|trader|founder|consultant"),
    ("Government / Public sector", r"govt|government|police|clerk|officer|\bias\b|\bips\b|railway|defen[cs]e|army"),
    ("Homemaker / Retired", r"homemaker|housewife|house wife|retired|home maker"),
]
_COMPILED = [(name, re.compile(rx, re.I)) for name, rx in OCCUPATION_GROUPS]
GROUP_ORDER = [name for name, _ in OCCUPATION_GROUPS] + ["Other"]

AGE_BANDS = [("Under 18", 0, 17), ("18-24", 18, 24), ("25-34", 25, 34), ("35-44", 35, 44), ("45-54", 45, 54), ("55+", 55, 200)]


def occupation_group(text):
    t = (text or "").strip()
    if not t:
        return "Other"
    for name, rx in _COMPILED:
        if rx.search(t):
            return name
    return "Other"


def _age(dob, today):
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _days(start_day, n):
    return [(start_day + timedelta(days=i)) for i in range(n)]


def _by_day(rows, days):
    """rows = [(day, count)] -> list of counts in the order of `days`, zero where nothing happened."""
    got = {str(d): c for d, c in rows}
    return [int(got.get(str(d), 0)) for d in days]


def build(days=DEFAULT_RANGE, now=None):
    days = days if days in RANGES else DEFAULT_RANGE
    now = now or datetime.now(timezone.utc)
    today = now.date()
    start = now - timedelta(days=days)
    first_day = today - timedelta(days=days - 1)
    day_list = _days(first_day, days)
    labels = [d.strftime("%d %b") for d in day_list]

    members = User.query.filter(User.role == "user")
    member_ids = db.session.query(User.id).filter(User.role == "user")
    total_members = members.count()
    active_accounts = members.filter(User.active.is_(True)).count()

    def seen_since(delta):
        return members.filter(User.active.is_(True), User.last_login >= now - delta).count()

    # ---- headline numbers
    new_in_range = members.filter(User.created_at >= start).count()
    chatters = (db.session.query(func.count(func.distinct(Message.user_id)))
                .filter(Message.deleted.is_(False), Message.created_at >= start, Message.user_id.in_(member_ids)).scalar() or 0)
    takers_in_range = (db.session.query(func.count(func.distinct(QuizAttempt.user_id)))
                       .filter(QuizAttempt.created_at >= start, QuizAttempt.user_id.in_(member_ids)).scalar() or 0)
    takers_ever = (db.session.query(func.count(func.distinct(QuizAttempt.user_id)))
                   .filter(QuizAttempt.user_id.in_(member_ids)).scalar() or 0)
    cards = OrderedDict([
        ("members", total_members),
        ("active_accounts", active_accounts),
        ("online_now", metrics.current()),
        ("active_24h", seen_since(timedelta(hours=24))),
        ("active_7d", seen_since(timedelta(days=7))),
        ("active_30d", seen_since(timedelta(days=30))),
        ("new_in_range", new_in_range),
        ("chatters", chatters),
        ("quiz_takers", takers_in_range),
    ])

    # ---- sign-ups per day
    signup_rows = (db.session.query(func.date(User.created_at), func.count(User.id))
                   .filter(User.role == "user", User.created_at >= datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc))
                   .group_by(func.date(User.created_at)).all())
    signups = _by_day(signup_rows, day_list)

    # ---- chat messages per day, and per room
    start_day_dt = datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc)
    msg_rows = (db.session.query(func.date(Message.created_at), func.count(Message.id))
                .filter(Message.deleted.is_(False), Message.created_at >= start_day_dt, Message.user_id.in_(member_ids))
                .group_by(func.date(Message.created_at)).all())
    messages = _by_day(msg_rows, day_list)
    room_rows = dict(db.session.query(Message.channel, func.count(Message.id))
                     .filter(Message.deleted.is_(False), Message.created_at >= start_day_dt, Message.user_id.in_(member_ids))
                     .group_by(Message.channel).all())
    rooms = [{"label": label, "value": int(room_rows.get(key, 0))} for key, label in Message.CHANNELS.items()]

    # ---- when members were last seen
    people = members.with_entities(User.id, User.occupation, User.dob, User.last_login, User.active).all()
    buckets = OrderedDict([("Today", 0), ("2-7 days ago", 0), ("8-30 days ago", 0), ("Over 30 days ago", 0), ("Never logged in", 0)])
    for _id, _occ, _dob, last, _active in people:
        if last is None:
            buckets["Never logged in"] += 1
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_days = (now - last).total_seconds() / 86400
        key = "Today" if age_days < 1 else "2-7 days ago" if age_days < 7 else "8-30 days ago" if age_days < 30 else "Over 30 days ago"
        buckets[key] += 1
    last_seen = [{"label": k, "value": v} for k, v in buckets.items()]

    # ---- occupation groups: how many members, how many have taken a quiz
    taker_ids = {uid for (uid,) in db.session.query(QuizAttempt.user_id).distinct().all()}
    members_by = Counter()
    takers_by = Counter()
    for uid, occ, dob, last, active in people:
        g = occupation_group(occ)
        members_by[g] += 1
        if uid in taker_ids:
            takers_by[g] += 1
    occupations = [{"label": g, "members": members_by[g], "quiz_takers": takers_by[g],
                    "rate": round(100 * takers_by[g] / members_by[g]) if members_by[g] else 0}
                   for g in GROUP_ORDER if members_by[g]]
    occupations.sort(key=lambda r: (-r["members"], r["label"]))

    # ---- age bands
    ages = Counter()
    for _id, _occ, dob, _last, _active in people:
        if not dob:
            ages["Not given"] += 1
            continue
        a = _age(dob, today)
        for label, lo, hi in AGE_BANDS:
            if lo <= a <= hi:
                ages[label] += 1
                break
        else:
            ages["Not given"] += 1
    age_rows = [{"label": label, "value": ages[label]} for label, _, _ in AGE_BANDS if ages[label]]
    if ages["Not given"]:
        age_rows.append({"label": "Not given", "value": ages["Not given"]})

    # ---- quizzes: attempts and average score for the latest ten
    quiz_rows = []
    for q in Quiz.query.filter(quiz_is_live()).order_by(Quiz.created_at.desc()).limit(10).all():
        n, avg = (db.session.query(func.count(QuizAttempt.id),
                                   func.avg(QuizAttempt.score * 100.0 / func.nullif(QuizAttempt.total, 0)))
                  .filter(QuizAttempt.quiz_id == q.id, QuizAttempt.user_id.in_(member_ids)).one())
        quiz_rows.append({"label": (q.title or "Quiz")[:40], "attempts": int(n or 0), "avg_score": round(float(avg or 0))})
    quiz_rows.reverse()  # oldest to newest, left to right

    return {
        "days": days,
        "ranges": list(RANGES),
        "generated": now.strftime("%d %b %Y %H:%M UTC"),
        "cards": cards,
        "quiz_participation": round(100 * takers_ever / total_members) if total_members else 0,
        "labels": labels,
        "signups": signups,
        "messages": messages,
        "rooms": rooms,
        "last_seen": last_seen,
        "occupations": occupations,
        "ages": age_rows,
        "quizzes": quiz_rows,
    }
