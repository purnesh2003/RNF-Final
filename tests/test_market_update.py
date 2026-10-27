"""Pre-market / post-market updates written by the admin, and the chat buttons that show them."""
from datetime import timedelta

from app import market_update as mu
from app.models import MarketUpdate
from tests.test_app import app, client, login, signup  # noqa: F401  (fixtures + helpers)

TEXT = "INDIAN MARKETS\n- Nifty closed higher\n- Sensex gained\n\nGLOBAL CUES\n- US markets ended mixed"


def admin_client(app):
    c = app.test_client()
    login(c, "member.admin@gmail.com", "adminpass12345")
    return c


def post(c, app, kind="pre", body=TEXT, day=None):
    with app.app_context():
        day = day or mu.today_local()
    return c.post("/admin/market-updates", data={"kind": kind, "for_date": day.isoformat(), "body": body}, follow_redirects=True)


def test_admin_publishes_and_members_read_it_with_the_buttons(app, client):
    assert client.get("/market-update/pre").status_code == 302  # login needed
    signup(client)
    assert client.get("/market-update/lunch").status_code == 404
    r = client.get("/market-update/pre")
    assert r.status_code == 404 and r.get_json()["ok"] is False  # nothing published yet
    assert b"Pre-market update published" in post(admin_client(app), app).data
    d = client.get("/market-update/pre").get_json()
    assert d["ok"] and d["label"] == "Pre-market update" and d["body"].startswith("INDIAN MARKETS")
    assert d["is_today"] is True and d["sources"] == []
    assert client.get("/market-update/post").status_code == 404  # the other button is still empty
    page = client.get("/community").get_data(as_text=True)
    assert "Pre-market update" in page and "Post-market update" in page and "market.js" in page


def test_saving_again_replaces_the_same_days_update_and_latest_wins(app, client):
    admin = admin_client(app)
    post(admin, app, body=TEXT)
    assert b"updated" in post(admin, app, body="CHANGED\n- new text for the day").data
    with app.app_context():
        assert MarketUpdate.query.count() == 1 and MarketUpdate.query.one().body.startswith("CHANGED")
        yesterday = mu.today_local() - timedelta(days=1)
    post(admin, app, body="OLD\n- yesterday's text here", day=yesterday)
    signup(client)
    assert client.get("/market-update/pre").get_json()["body"].startswith("CHANGED")  # newest day shown


def test_bad_input_is_rejected(app):
    admin = admin_client(app)
    with app.app_context():
        today = mu.today_local()
    assert admin.post("/admin/market-updates", data={"kind": "pre", "for_date": today.isoformat(), "body": "hi"}).status_code == 400
    assert admin.post("/admin/market-updates", data={"kind": "lunch", "for_date": today.isoformat(), "body": TEXT}).status_code == 400
    assert admin.post("/admin/market-updates", data={"kind": "pre", "for_date": "not-a-date", "body": TEXT}).status_code == 400
    far = (today + timedelta(days=10)).isoformat()
    assert admin.post("/admin/market-updates", data={"kind": "pre", "for_date": far, "body": TEXT}).status_code == 400
    with app.app_context():
        assert MarketUpdate.query.count() == 0


def test_html_is_stripped_and_edit_and_delete_work(app, client):
    admin = admin_client(app)
    post(admin, app, body="HEADING\n- <script>alert(1)</script>**bold** point here")
    with app.app_context():
        row = MarketUpdate.query.one()
        assert "<" not in row.body and "**" not in row.body
        uid = row.id
    assert b"HEADING" in admin.get(f"/admin/market-updates?edit={uid}").data  # edit loads the text into the form
    admin.post(f"/admin/market-updates/{uid}/delete")
    with app.app_context():
        assert MarketUpdate.query.count() == 0


def test_members_cannot_use_the_admin_page(app, client):
    signup(client)
    assert client.get("/admin/market-updates").status_code in (302, 403)
    assert client.post("/admin/market-updates", data={"kind": "pre", "for_date": "2026-10-27", "body": TEXT}).status_code in (302, 403)
    with app.app_context():
        assert MarketUpdate.query.count() == 0
