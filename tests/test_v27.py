"""Referral links and scheduled posts/quizzes."""
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
    form = {"name": "Ben", "email": "ben.friend@gmail.com", "dob": "2000-01-01", "occupation": "Dev", "phone": "9876543210",
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
    r = client.post("/register", data={"name": "Cy", "email": "cy.person@gmail.com", "dob": "2000-01-01", "occupation": "X", "phone": "9876543210",
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


# ------------------------------------------------------------ disclaimer
def test_disclaimer_page_and_footer_are_public(app, client):
    r = client.get("/disclaimer")
    assert r.status_code == 200 and b"not a SEBI registered advisor" in r.data
    home = client.get("/").get_data(as_text=True)
    assert "SEBI registered advisor" in home and "/disclaimer" in home
    assert "SEBI registered advisor" in client.get("/register").get_data(as_text=True)


# ------------------------------------------------------------ one Calculator tab (SIP + SWP inside), wording
def test_one_calculator_tab_with_sip_and_swp_inside_for_everyone(app, client):
    home = client.get("/").get_data(as_text=True)  # logged out
    assert 'class="nav-link" href="/calculator">Calculator<' in home
    assert "/swp-calculator" not in home and "btn-calc" not in home and "nav-calc" not in home and "calc-float" not in home
    assert "free market insights" not in home.lower() and "market insights are free" not in home.lower()
    r = client.get("/calculator")
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and 'nav-link active" href="/calculator"' in page
    assert 'data-calc="sip"' in page and 'data-calc="swp"' in page and "calculator.js" in page
    for label in ("Final amount required", "Monthly SIP required",                     # SIP half
                  "Total investment", "Withdrawal per month", "Final value", "Time period"):  # SWP half
        assert label in page
    signup(client)
    assert 'href="/calculator"' in client.get("/news").get_data(as_text=True)


def test_old_calculator_addresses_redirect_to_the_one_page(app, client):
    r = client.get("/sip-calculator")
    assert r.status_code == 302 and r.headers["Location"].endswith("/calculator#sip")
    r = client.get("/swp-calculator")
    assert r.status_code == 302 and r.headers["Location"].endswith("/calculator#swp")


# ------------------------------------------------------------ mobile number at sign-up
def _reg(client, **over):
    data = {"name": "Dev", "email": "dev.person@gmail.com", "dob": "2000-01-01", "occupation": "Dev",
            "phone": "9876543210", "password": "Password@12345", "confirm": "Password@12345"}
    data.update(over)
    return client.post("/register", data=data)


def test_signup_needs_a_valid_indian_mobile(app, client):
    for bad in ("", "12345", "5876543210", "98765432101", "abcdefghij", "9999999999", "+91 12345 67890"):
        assert _reg(client, phone=bad).status_code == 400, bad
    with app.app_context():
        assert User.query.filter_by(email="dev.person@gmail.com").count() == 0
    assert b"10-digit Indian mobile" in _reg(client, phone="123").data
    assert b'name="phone"' in client.get("/register").data


def test_mobile_is_saved_as_ten_digits(app, client):
    for raw in ("+91 98765-43210", "09876543210", "98765 43210"):
        with app.app_context():
            User.query.filter_by(email="dev.person@gmail.com").delete()
            db.session.commit()
        assert _reg(client, phone=raw).status_code == 302, raw
        with app.app_context():
            assert User.query.filter_by(email="dev.person@gmail.com").one().phone == "9876543210"


def test_admin_sees_mobile_in_list_and_csv(app, client):
    _reg(client)
    admin = admin_client(app)
    assert b"9876543210" in admin.get("/admin/users").data
    assert b"9876543210" in admin.get("/admin/users.csv").data
