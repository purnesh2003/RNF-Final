"""AI quiz generation, e-mail announcement and the home-page quiz card."""
import json
import urllib.error

import pytest

from app import gemini_quiz
from app.extensions import db
from app.models import Question, Quiz, QuizAttempt, User
from tests.test_app import app, client, login, make_quiz, signup  # noqa: F401  (fixtures)

ADMIN = ("member.admin@gmail.com", "adminpass12345")


def good_payload(n=3, topic="Mutual funds"):
    return {"questions": [{
        "question_text": f"Question number {i} about funds?",
        "options": {"A": f"a{i}", "B": f"b{i}", "C": f"c{i}", "D": f"d{i}"},
        "correct_answer": "B", "explanation": f"because {i}", "difficulty": "Medium", "topic": topic,
    } for i in range(1, n + 1)]}


@pytest.fixture()
def ai_app(app):
    app.config.update(GEMINI_API_KEY="test-key-123", QUIZ_NOTIFY_EMAILS=True)
    return app


def admin_client(app):
    c = app.test_client()
    login(c, *ADMIN)
    return c


def fake_gemini(monkeypatch, payload=None, text=None, error=None):
    calls = []

    def fake_post(prompt, api_key, model, timeout):
        calls.append((prompt, api_key))
        if error:
            raise error
        return text if text is not None else json.dumps(payload)

    monkeypatch.setattr(gemini_quiz, "_post", fake_post)
    monkeypatch.setattr(gemini_quiz.time, "sleep", lambda s: None)
    return calls


def gen(c, **over):
    body = {"topic": "Mutual funds", "count": 3, "difficulty": "medium", **over}
    return c.post("/admin/quizzes/generate", json=body)


# ---------------------------------------------------------------- generation
def test_generate_success_returns_validated_draft_and_saves_nothing(ai_app, monkeypatch):
    calls = fake_gemini(monkeypatch, good_payload(3))
    r = gen(admin_client(ai_app))
    d = r.get_json()
    assert r.status_code == 200 and d["ok"] and len(d["questions"]) == 3
    q = d["questions"][0]
    assert len(q["options"]) == 4 and q["options"][q["correct"]].startswith("b")  # shuffled, still right
    assert q["explanation"] == "because 1"
    assert "exactly 3 multiple-choice" in calls[0][0] and "Mutual funds" in calls[0][0]
    with ai_app.app_context():
        assert Quiz.query.count() == 0  # a draft is never stored until the admin publishes


@pytest.mark.parametrize("error,status", [
    (urllib.error.URLError("down"), 502),
    (TimeoutError("slow"), 502),
])
def test_generate_failure_is_friendly_and_creates_nothing(ai_app, monkeypatch, error, status):
    fake_gemini(monkeypatch, error=error)
    r = gen(admin_client(ai_app))
    assert r.status_code == status and r.get_json()["ok"] is False
    assert "Traceback" not in r.get_data(as_text=True) and "test-key-123" not in r.get_data(as_text=True)
    with ai_app.app_context():
        assert Quiz.query.count() == 0


def test_rate_limit_and_server_errors_are_retried_then_reported(ai_app, monkeypatch):
    attempts = []

    def boom(*a, **k):
        attempts.append(1)
        raise urllib.error.HTTPError("https://x", 429, "Too Many", {}, None)

    monkeypatch.setattr(gemini_quiz, "_post", boom)
    monkeypatch.setattr(gemini_quiz.time, "sleep", lambda s: None)
    r = gen(admin_client(ai_app))
    assert len(attempts) == 3 and r.status_code == 502 and "rate limit" in r.get_json()["error"]


def test_bad_key_is_not_retried(ai_app, monkeypatch):
    attempts = []

    def deny(*a, **k):
        attempts.append(1)
        raise urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)

    monkeypatch.setattr(gemini_quiz, "_post", deny)
    r = gen(admin_client(ai_app))
    assert len(attempts) == 1 and r.status_code == 502
    assert "test-key-123" not in r.get_data(as_text=True)


@pytest.mark.parametrize("text", [
    "not json at all",
    json.dumps({"questions": "nope"}),
    json.dumps({"questions": []}),
])
def test_invalid_gemini_response_rejected(ai_app, monkeypatch, text):
    fake_gemini(monkeypatch, text=text)
    r = gen(admin_client(ai_app))
    assert r.status_code == 502 and r.get_json()["ok"] is False
    with ai_app.app_context():
        assert Quiz.query.count() == 0


def test_validation_rules():
    base = good_payload(3)["questions"]
    dup_opts = dict(base[0], options={"A": "x", "B": "X", "C": "y", "D": "z"})        # repeated option
    three = dict(base[1], options={"A": "1", "B": "2", "C": "3"})                     # only 3 options
    bad_letter = dict(base[2], correct_answer="E")
    with pytest.raises(gemini_quiz.QuizGenerationError):
        gemini_quiz.validate_questions({"questions": [dup_opts, three, bad_letter]}, 3)
    # duplicates and malformed items are skipped; enough good ones remain -> accepted
    twin = dict(base[0])
    out = gemini_quiz.validate_questions({"questions": [base[0], twin, three, base[1], base[2]]}, 3)
    assert len(out) == 3
    # too few usable questions -> whole result rejected (no half-quiz)
    with pytest.raises(gemini_quiz.QuizGenerationError):
        gemini_quiz.validate_questions({"questions": [base[0], twin]}, 2)


def test_generated_text_is_stripped_of_markup():
    p = good_payload(1)
    p["questions"][0]["question_text"] = "What is <script>alert(1)</script>an SIP?"
    p["questions"][0]["explanation"] = "<b>Bold</b> text"
    q = gemini_quiz.validate_questions(p, 1)[0]
    assert "<" not in q["text"] and "alert(1)" in q["text"] and q["explanation"] == "Bold text"


def test_code_fenced_json_is_tolerated():
    assert gemini_quiz._extract_json("```json\n" + json.dumps(good_payload(1)) + "\n```")["questions"]


def test_input_validation(ai_app, monkeypatch):
    fake_gemini(monkeypatch, good_payload(3))
    c = admin_client(ai_app)
    assert gen(c, topic="").status_code == 400
    assert gen(c, count=0).status_code == 400
    assert gen(c, count=999).status_code == 400
    assert gen(c, difficulty="extreme").status_code == 400


def test_missing_api_key_gives_setup_hint(app, monkeypatch):
    app.config["GEMINI_API_KEY"] = ""
    r = gen(admin_client(app))
    assert r.status_code == 400 and "GEMINI_API_KEY" in r.get_json()["error"]


def test_unauthorised_generation(ai_app, client, monkeypatch):
    calls = fake_gemini(monkeypatch, good_payload(3))
    assert client.post("/admin/quizzes/generate", json={"topic": "x"}).status_code in (302, 401, 403)  # anonymous
    signup(client)
    assert gen(client).status_code == 403  # ordinary member
    assert calls == []  # Gemini was never called


def test_api_key_never_reaches_the_browser(ai_app):
    html = admin_client(ai_app).get("/admin/quizzes/new").get_data(as_text=True)
    assert "test-key-123" not in html and "GEMINI_API_KEY" in html or "Generate with AI" in html
    assert "test-key-123" not in html


def test_key_goes_in_header_not_url(monkeypatch):
    seen = {}

    class Resp:
        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(req, timeout):
        seen["url"], seen["headers"], seen["timeout"] = req.full_url, dict(req.header_items()), timeout
        return Resp()

    monkeypatch.setattr(gemini_quiz.urllib.request, "urlopen", fake_open)
    gemini_quiz._post("hi", "SECRET-KEY", "gemini-3.8-flash", 7)
    assert "SECRET-KEY" not in seen["url"] and seen["headers"]["X-goog-api-key"] == "SECRET-KEY" and seen["timeout"] == 7


# ---------------------------------------------------------------- publish, take, score
def publish_ai(c, n=3):
    qs = [{"text": f"Q{i}?", "options": ["w", "right", "x", "y"], "correct": 1, "explanation": f"why {i}"}
          for i in range(1, n + 1)]
    return c.post("/admin/quizzes/new", data={
        "title": "AI quiz", "description": "d", "questions_json": json.dumps(qs),
        "source": "ai", "topic": "Funds", "difficulty": "hard"}, follow_redirects=True)


def test_publish_ai_quiz_creates_quiz_and_questions(ai_app):
    assert publish_ai(admin_client(ai_app)).status_code == 200
    with ai_app.app_context():
        q = Quiz.query.one()
        assert (q.source, q.topic, q.difficulty) == ("ai", "Funds", "hard")
        assert [x.explanation for x in q.questions] == ["why 1", "why 2", "why 3"]
        assert Question.query.count() == 3 and all(len(x.options) == 4 for x in q.questions)


def test_submission_scores_on_the_server_and_ignores_tampering(ai_app, client):
    publish_ai(admin_client(ai_app))
    signup(client)
    page = client.get("/quizzes/1").get_data(as_text=True)
    assert "why 1" not in page and "correct_index" not in page  # answers/explanations not sent before submit
    r = client.post("/quizzes/1", data={"q1": "1", "q2": "0", "q3": "1", "score": "3", "correct_index": "0"})
    html = r.get_data(as_text=True)
    assert "2 / 3" in html and "1 wrong" in html and "67%" in html and "why 2" in html
    with ai_app.app_context():
        a = QuizAttempt.query.one()
        assert (a.score, a.total) == (2, 3)


def test_existing_quiz_works_when_gemini_is_down(ai_app, client, monkeypatch):
    admin = admin_client(ai_app)
    make_quiz(admin)  # a hand-made quiz stored earlier
    fake_gemini(monkeypatch, error=urllib.error.URLError("offline"))
    assert gen(admin).status_code == 502
    signup(client)
    assert b"2+2?" in client.get("/quizzes/1").data
    assert b"1 / 2" in client.post("/quizzes/1", data={"q1": "1", "q2": "1"}).data
    assert b"Basics" in client.get("/quizzes").data


def test_manual_quiz_still_works_without_ai(app):
    assert make_quiz(admin_client(app)).status_code == 200
    with app.app_context():
        assert Quiz.query.one().source == "manual"


# ---------------------------------------------------------------- e-mail announcement
@pytest.fixture()
def mailbox(ai_app, monkeypatch):
    sent = []
    import app.quiz_notify as qn
    monkeypatch.setattr(qn, "mail_configured", lambda: True)
    import app.notify as nt

    def send_each(items):
        for to, subj, text, html in items:
            sent.append((to, subj, text, None))   # last slot = bcc: never used any more, one mail per member
        return len(sent)

    monkeypatch.setattr(nt.mailer, "send_each", send_each)
    return sent


def test_members_are_emailed_when_a_quiz_is_created(ai_app, client, mailbox):
    signup(client, email="one.member@gmail.com", name="One")
    signup(app_client := ai_app.test_client(), email="two.member@gmail.com", name="Two")
    with ai_app.app_context():  # a suspended member must not get mail
        u = User.query.filter_by(email="two.member@gmail.com").one()
        u.active = False
        db.session.commit()
    publish_ai(admin_client(ai_app))
    tos = [m[0] for m in mailbox]
    assert "one.member@gmail.com" in tos and "member.admin@gmail.com" in tos and "two.member@gmail.com" not in tos
    assert len(mailbox) == len(set(tos)) == 2          # one personal message each
    to, subject, text, bcc = next(m for m in mailbox if m[0] == "one.member@gmail.com")
    assert subject == "New quiz: AI quiz" and "/quizzes/1" in text and text.startswith("Hi One,") and not bcc
    with ai_app.app_context():
        assert Quiz.query.one().notified_at is not None


def test_long_title_gives_short_subject(ai_app):
    from app import quiz_notify
    class Q: title = "Economic Analysis covers the study of various economic factors that influence businesses, industries, financial markets"; difficulty = None; questions = []; description = ""; id = 1
    with ai_app.test_request_context():
        subject, _, _ = quiz_notify._compose(Q, "http://x/q")
    assert len(subject) < 90 and subject.endswith("...")


def test_quiz_is_announced_only_once(ai_app, mailbox):
    from app import quiz_notify
    publish_ai(admin_client(ai_app))
    with ai_app.test_request_context():
        assert quiz_notify.announce_quiz(1) is False
    assert len(mailbox) == 1


def test_no_mail_when_mail_is_not_configured_but_quiz_is_still_published(ai_app, client):
    signup(client)
    publish_ai(admin_client(ai_app))  # no SMTP in tests: must not fail
    with ai_app.app_context():
        assert Quiz.query.count() == 1


def test_notification_can_be_switched_off(ai_app, mailbox):
    ai_app.config["QUIZ_NOTIFY_EMAILS"] = False
    publish_ai(admin_client(ai_app))
    assert mailbox == []


# ---------------------------------------------------------------- home page
def test_home_shows_quiz_card_not_stocks_card(ai_app, client):
    signup(client)
    html = client.get("/").get_data(as_text=True)
    assert "dk-title\">Quiz<" in html and "dk-title\">Stocks<" not in html
    assert "No quiz yet" in html
    publish_ai(admin_client(ai_app))
    html = client.get("/").get_data(as_text=True)
    assert "AI quiz" in html and "Start Quiz" in html
    client.post("/quizzes/1", data={"q1": "1", "q2": "1", "q3": "1"})
    assert "<strong>3/3</strong>" in client.get("/").get_data(as_text=True)


def test_stocks_section_still_exists(client):
    signup(client)
    assert client.get("/stocks").status_code == 200


def test_home_quiz_card_for_visitors(client):
    html = client.get("/").get_data(as_text=True)
    assert "Log in to take the latest quiz" in html


# ---------------------------------------------------------------- admin posts / community e-mails, SIP page
@pytest.fixture()
def post_mail(ai_app, monkeypatch):
    sent = []
    import app.notify as nt
    monkeypatch.setattr(nt.mailer, "mail_configured", lambda: True)
    monkeypatch.setattr(nt.mailer, "send_mail", lambda to, subj, text, html=None, bcc=None: sent.append((to, subj, text)) or True)

    def send_each(items):
        for t, s, x, h in items:
            sent.append((t, s, x))
        return len(sent)

    monkeypatch.setattr(nt.mailer, "send_each", send_each)
    ai_app.config.update(ADMIN_POST_EMAILS=True)
    return sent


def test_admin_feed_post_emails_members_personally(ai_app, client, post_mail):
    signup(client, email="one.member@gmail.com", name="One Smith")
    r = admin_client(ai_app).post("/admin/posts/new", data={"title": "Market update", "body": "Nifty is up", "section": "news",
                                                           "category": "news"}, follow_redirects=True)
    assert r.status_code == 200
    tos = [m[0] for m in post_mail]
    assert tos == ["one.member@gmail.com"]                       # members only, not the admin, one mail each
    assert post_mail[0][1] == "New from the admin: Market update" and post_mail[0][2].startswith("Hi One,")


def test_admin_community_file_emails_but_member_messages_do_not(ai_app, client, post_mail):
    import io
    signup(client, email="one.member@gmail.com", name="One")
    client.post("/community/upload", data={"file": (io.BytesIO(b"x"), "a.txt"), "caption": "hello"},
                content_type="multipart/form-data")
    assert post_mail == []                                       # a member's own upload never mails anyone
    a = admin_client(ai_app)
    a.post("/community/upload", data={"file": (io.BytesIO(b"x"), "notes.txt"), "caption": "Read this"},
           content_type="multipart/form-data")
    assert [m[0] for m in post_mail] == ["one.member@gmail.com"]
    assert "notes.txt" in post_mail[0][2]


def test_post_emails_can_be_switched_off(ai_app, client, post_mail):
    ai_app.config.update(ADMIN_POST_EMAILS=False)
    signup(client, email="one.member@gmail.com", name="One")
    admin_client(ai_app).post("/admin/posts/new", data={"title": "T", "body": "B", "section": "home", "category": "news"})
    assert post_mail == []


def test_calculator_is_public_and_menu_has_the_tab(ai_app, client):
    r = client.get("/calculator")
    assert r.status_code == 200 and b"SIP Calculator" in r.data and b"SWP Calculator" in r.data
    home = client.get("/").data
    assert b'href="/calculator"' in home and b"whatsapp" not in home.lower()
