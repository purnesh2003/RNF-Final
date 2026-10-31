"""Forced password change, and logins that survive a changing IP address (phones on mobile data)."""
from app.extensions import db
from app.models import User
from tests.test_app import app, client, login, signup  # noqa: F401  (fixtures + helpers)


def test_forced_password_change_saves_and_clears_the_flag(app):
    admin = app.test_client()
    login(admin, "member.admin@gmail.com", "adminpass12345")
    with app.app_context():
        u = User.query.filter_by(email="member.admin@gmail.com").one()
        u.must_change_password = True
        db.session.commit()
    assert admin.get("/").status_code == 302  # sent to the change-password page
    r = admin.post("/account/password", data={"current": "adminpass12345", "password": "N3w-Strong#Pass99",
                                              "confirm": "N3w-Strong#Pass99"}, follow_redirects=True)
    assert r.status_code == 200 and b"Password updated" in r.data
    with app.app_context():
        u = User.query.filter_by(email="member.admin@gmail.com").one()
        assert not u.must_change_password and u.check_password("N3w-Strong#Pass99")
    assert admin.get("/").status_code == 200  # still signed in, no second prompt
    other = app.test_client()  # e.g. the phone
    login(other, "member.admin@gmail.com", "N3w-Strong#Pass99")
    assert other.get("/").status_code == 200


def test_login_survives_an_ip_change(app):
    c = app.test_client()
    r = c.post("/login", data={"email": "member.admin@gmail.com", "password": "adminpass12345"},
               environ_base={"REMOTE_ADDR": "10.1.1.1"})
    assert r.status_code == 302
    r = c.get("/community", environ_base={"REMOTE_ADDR": "10.9.9.9"})  # mobile data moved to another address
    assert r.status_code == 200


def test_missing_csrf_token_shows_a_friendly_retry(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    r = c.post("/login", data={"email": "member.admin@gmail.com", "password": "adminpass12345"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")  # not a bare "Bad Request"
    page = c.get("/login")
    assert b"out of date" in page.data and page.headers["Cache-Control"] == "no-store"
