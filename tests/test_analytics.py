"""Admin analytics: access control, the numbers, and the grouping of typed-in occupations."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app import analytics
from app.extensions import db
from app.models import Message, Quiz, QuizAttempt, User
from tests.test_app import app, client, login  # noqa: F401  (fixtures)


def add_user(email, name, occupation, dob=None, last_login=None, created=None, role="user"):
    u = User(name=name, email=email, occupation=occupation, dob=dob, role=role, last_login=last_login)
    if created:
        u.created_at = created
    u.set_password("Password@12345")
    db.session.add(u)
    db.session.commit()
    return u


def seed(app):
    """Three members + one admin-only quiz and a few attempts/messages. Returns nothing; use build()."""
    now = datetime.now(timezone.utc)
    with app.app_context():
        a = add_user("a@gmail.com", "Asha", "Engineering student", date(2003, 4, 1), now - timedelta(hours=2), now - timedelta(days=1))
        b = add_user("b@gmail.com", "Bala", "Software developer", date(1995, 6, 1), now - timedelta(days=3), now - timedelta(days=5))
        c = add_user("c@gmail.com", "Chitra", "Teacher", None, None, now - timedelta(days=40))
        admin = User.query.filter_by(role="admin").one()
        admin.last_login = now
        q = Quiz(title="Basics")
        db.session.add(q)
        db.session.commit()
        db.session.add_all([
            QuizAttempt(quiz_id=q.id, user_id=a.id, score=2, total=2, answers={}),
            QuizAttempt(quiz_id=q.id, user_id=b.id, score=1, total=2, answers={}),
            QuizAttempt(quiz_id=q.id, user_id=admin.id, score=0, total=2, answers={}),  # admin must not count
            Message(user_id=a.id, body="hi", channel="general"),
            Message(user_id=a.id, body="again", channel="investors"),
            Message(user_id=b.id, body="yo", channel="general"),
            Message(user_id=admin.id, body="announcement", channel="general"),
        ])
        db.session.commit()


def test_anonymous_and_members_cannot_open_analytics(app, client):
    assert client.get("/admin/analytics").status_code in (302, 401)
    with app.app_context():
        add_user("m@gmail.com", "Mem", "Student")
    login(client, "m@gmail.com", "Password@12345")
    assert client.get("/admin/analytics").status_code == 403


def test_admin_sees_the_page_with_data_and_all_ranges(app, client):
    seed(app)
    login(client, "member.admin@gmail.com", "adminpass12345")
    for days in (7, 30, 90):
        r = client.get(f"/admin/analytics?days={days}")
        assert r.status_code == 200
        assert b"Analytics" in r.data and b'id="analytics-data"' in r.data and b"analytics.js" in r.data
    # odd values fall back to the default range instead of failing
    assert client.get("/admin/analytics?days=abc").status_code == 200
    assert client.get("/admin/analytics?days=9999").status_code == 200


def test_admin_menu_links_to_analytics(app, client):
    login(client, "member.admin@gmail.com", "adminpass12345")
    assert b"/admin/analytics" in client.get("/admin/").data


def test_numbers(app):
    seed(app)
    with app.app_context():
        d = analytics.build(30)
    c = d["cards"]
    assert c["members"] == 3                      # admin is not counted
    assert c["active_24h"] == 1 and c["active_7d"] == 2 and c["active_30d"] == 2
    assert c["new_in_range"] == 2                 # Chitra joined 40 days ago
    assert c["chatters"] == 2 and c["quiz_takers"] == 2
    assert sum(d["signups"]) == 2 and len(d["signups"]) == len(d["labels"]) == 30
    assert sum(d["messages"]) == 3 and {r["label"]: r["value"] for r in d["rooms"]}["General"] == 2   # admin posts not counted
    occ = {r["label"]: r for r in d["occupations"]}
    assert occ["Student"]["members"] == 1 and occ["Student"]["quiz_takers"] == 1 and occ["Student"]["rate"] == 100
    assert occ["Engineer"]["members"] == 1 and occ["Teacher / Professor"]["quiz_takers"] == 0
    assert d["quiz_participation"] == 67          # 2 of 3 members
    seen = {r["label"]: r["value"] for r in d["last_seen"]}
    assert seen["Today"] == 1 and seen["2-7 days ago"] == 1 and seen["Never logged in"] == 1
    ages = {r["label"]: r["value"] for r in d["ages"]}
    assert ages["Not given"] == 1 and sum(ages.values()) == 3
    q = d["quizzes"][0]
    assert q["label"] == "Basics" and q["attempts"] == 2 and q["avg_score"] == 75   # (100% + 50%) / 2; admin ignored


def test_empty_site_does_not_crash(app):
    with app.app_context():
        d = analytics.build(7)
    assert d["cards"]["members"] == 0 and d["quiz_participation"] == 0 and d["occupations"] == [] and d["quizzes"] == []


@pytest.mark.parametrize("typed, group", [
    ("Student", "Student"), ("engineering student", "Student"), ("B.Tech 3rd year", "Student"),
    ("Software Engineer", "Engineer"), ("software developer", "Engineer"), ("IT", "Engineer"),
    ("teacher", "Teacher / Professor"), ("Doctor", "Doctor / Healthcare"), ("CA", "Finance / Accounting"),
    ("Bank manager", "Finance / Accounting"), ("Business owner", "Business / Self-employed"),
    ("Govt employee", "Government / Public sector"), ("Housewife", "Homemaker / Retired"),
    ("", "Other"), (None, "Other"), ("Photographer", "Other"),
])
def test_occupation_grouping(typed, group):
    assert analytics.occupation_group(typed) == group
