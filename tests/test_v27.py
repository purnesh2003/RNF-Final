"""Referral links, scheduled posts/quizzes, and search."""
import json
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Message, Post, Quiz, User
from tests.test_app import app, client, login, signup  # noqa: F401  (fixtures + helpers)


def admin_client(app):
    c = app.test_client()
    login(c, "member.admin@gmail.com", "adminpass12345")
    return c


def local_in(app, hours):
    """A datetime-local value (in the site's schedule time zone) `hours` from now."""
    from app import scheduler
    with app.app_context():
        return scheduler.to_local(datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


# ------------------------------------------------------------ referral
def test_referral_link_counts_only_confirmed_friends(app, client):
    signup(client)
    page = client.get("/invite")
    assert page.status_code == 200
    with app.app_context():
        code = User.query.filter_by(email="member.a@gmail.com").one().referral_code
    assert code and f"ref={code}" in page.get_data(as_text=True)
    assert b"0</div>" in page.data

    friend = app.test_client()
    form = {"name": "Ben", "email": "ben.friend@gmail.com", "dob": "2000-01-01", "occupation": "Dev",
            "password": "Password@12345", "confirm": "Password@12345", "ref": code}
    assert friend.post("/register", data=form).status_code == 302
    assert b"waiting to confirm" in client.get("/invite").data  # not counted until the email is confirmed
    signup(friend, email="ben.friend@gmail.com")  # re-register + confirm (same address)
    with app.app_context():
        ben = User.query.filter_by(email="ben.friend@gmail.com").one()
        assert ben.referred_by_id == User.query.filter_by(email="member.a@gmail.com").one().id
    body = client.get("/invite").get_data(as_text=True)
    assert "friend joined" in body and "Ben" in body


def test_bad_referral_code_is_ignored_and_register_page_keeps_it(app, client):
    assert b'name="ref" value="ABC12345"' in client.get("/register?ref=abc12345").data
    r = client.post("/register", data={"name": "Cy", "email": "cy.person@gmail.com", "dob": "2000-01-01", "occupation": "X",
                                       "password": "Password@12345", "confirm": "Password@12345", "ref": "NOSUCH"})
    assert r.status_code == 302
    with app.app_context():
        assert User.query.filter_by(email="cy.person@gmail.com").one().referred_by_id is None


def test_invite_needs_login(client):
    assert client.get("/invite").status_code == 302


# ------------------------------------------------------------ scheduling
def test_scheduled_post_hidden_until_due_then_appears(app, client):
    admin = admin_client(app)
    r = admin.post("/admin/posts/new", data={"title": "Later post", "body": "secret plan", "section": "home",
                                             "category": "news", "publish_at": local_in(app, 2)}, follow_redirects=True)
    assert b"Scheduled for" in r.data and b"Later post" in r.data  # shown on the admin Scheduled page
    signup(client)
    assert b"Later post" not in client.get("/").data
    assert b"Later post" not in client.get("/opinions").data
    assert b"Later post" not in client.get("/search?q=secret").data
    with app.app_context():
        p = Post.query.filter_by(title="Later post").one()
        assert p.publish_at is not None and p.notified_at is None
        p.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)  # the time arrives
        db.session.commit()
        from app import scheduler
        assert scheduler.publish_due() == 1
        assert scheduler.publish_due() == 0  # never announced twice
        assert Post.query.filter_by(title="Later post").one().notified_at is not None
    assert b"Later post" in client.get("/").data


def test_publish_time_must_be_in_future(app):
    admin = admin_client(app)
    past = local_in(app, -1)
    r = admin.post("/admin/posts/new", data={"title": "x", "body": "y", "section": "home", "category": "news", "publish_at": past})
    assert r.status_code == 400
    with app.app_context():
        assert Post.query.count() == 0


def test_scheduled_quiz_hidden_then_open_and_cancel(app, client):
    admin = admin_client(app)
    qs = [{"text": "2+2?", "options": ["3", "4"], "correct": 1}]
    r = admin.post("/admin/quizzes/new", data={"title": "Timed quiz", "questions_json": json.dumps(qs), "publish_at": local_in(app, 3)},
                   follow_redirects=True)
    assert b"Quiz scheduled" in r.data
    signup(client)
    assert b"Timed quiz" not in client.get("/quizzes").data
    with app.app_context():
        qid = Quiz.query.filter_by(title="Timed quiz").one().id
    assert client.get(f"/quizzes/{qid}").status_code == 404
    admin.post(f"/admin/scheduled/quiz/{qid}/now")
    assert b"Timed quiz" in client.get("/quizzes").data
    assert client.get(f"/quizzes/{qid}").status_code == 200
    # cancel a scheduled post
    admin.post("/admin/posts/new", data={"title": "Cancel me", "body": "b", "section": "news", "category": "news", "publish_at": local_in(app, 2)})
    with app.app_context():
        pid = Post.query.filter_by(title="Cancel me").one().id
    admin.post(f"/admin/scheduled/post/{pid}/cancel")
    with app.app_context():
        assert db.session.get(Post, pid) is None


def test_members_cannot_use_scheduled_admin_pages(app, client):
    signup(client)
    assert client.get("/admin/scheduled").status_code in (302, 403)
    assert client.post("/admin/scheduled/post/1/now").status_code in (302, 403)


# ------------------------------------------------------------ search
def test_search_posts_documents_and_chat(app, client):
    admin = admin_client(app)
    admin.post("/admin/posts/new", data={"title": "Nifty outlook", "body": "Markets look calm", "section": "stocks", "category": "news"})
    signup(client)
    with app.app_context():
        uid = User.query.filter_by(email="member.a@gmail.com").one().id
        db.session.add(Message(user_id=uid, body="Anyone watching Nifty today?", channel="traders"))
        db.session.add(Message(user_id=uid, body="report", file_key="a" * 32 + ".pdf", file_name="Nifty-report.pdf",
                               file_mime="application/pdf", channel="general"))
        db.session.add(Message(user_id=uid, body="Nifty deleted", channel="general", deleted=True))
        db.session.commit()
    body = client.get("/search?q=nifty").get_data(as_text=True)
    assert "Nifty outlook" in body and "Anyone watching Nifty today?" in body and "Nifty-report.pdf" in body
    assert "Nifty deleted" not in body
    only_chat = client.get("/search?q=nifty&in=chat").get_data(as_text=True)
    assert "Anyone watching" in only_chat and "Nifty outlook" not in only_chat
    assert b"No results" in client.get("/search?q=zzzzqq").data
    assert b"at least 2" in client.get("/search?q=a").data


def test_search_treats_percent_literally_and_needs_login(app, client):
    assert client.get("/search?q=nifty").status_code == 302
    signup(client)
    assert b"No results" in client.get("/search?q=%25%25").data  # "%%" must not match everything


# ------------------------------------------------------------ disclaimer
def test_disclaimer_page_and_footer_are_public(app, client):
    r = client.get("/disclaimer")
    assert r.status_code == 200 and b"not a SEBI registered advisor" in r.data
    home = client.get("/").get_data(as_text=True)
    assert "SEBI registered advisor" in home and "/disclaimer" in home
    assert "SEBI registered advisor" in client.get("/register").get_data(as_text=True)


# ------------------------------------------------------------ calculator tab, wording
def test_calculator_tab_is_visible_to_everyone_and_free_insights_wording_is_gone(app, client):
    home = client.get("/").get_data(as_text=True)  # logged out
    assert 'class="nav-link nav-calc"' in home and "/sip-calculator" in home and "btn-calc" in home
    assert "free market insights" not in home.lower() and "market insights are free" not in home.lower()
    signup(client)
    assert 'nav-calc' in client.get("/news").get_data(as_text=True)
    assert "nav-calc active" in client.get("/sip-calculator").get_data(as_text=True)


def test_swp_calculator_is_public_and_linked_from_both_calculator_pages(app, client):
    r = client.get("/swp-calculator")  # logged out
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "SWP Calculator" in page and "swp.js" in page
    for label in ("Total investment", "Withdrawal per month", "Expected return rate", "Time period", "Final value"):
        assert label in page
    assert "calc-tab active" in page and "/sip-calculator" in page  # tab switcher, SWP tab active
    sip = client.get("/sip-calculator").get_data(as_text=True)
    assert "/swp-calculator" in sip and "calc-tabs" in sip
    assert "nav-calc active" in page and "Calculators" in page
