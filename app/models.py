from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


def _iso_utc(dt):
    """SQLite hands back naive datetimes; treat them as UTC so browsers show the right local time."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())  # kept for older databases; no longer used
    dob = db.Column(db.Date)                      # collected at sign-up (null for admin/legacy accounts)
    occupation = db.Column(db.String(100))        # collected at sign-up
    password_hash = db.Column(db.String(255), nullable=False)  # never the plain password
    role = db.Column(db.String(20), nullable=False, default="user")  # user | admin
    active = db.Column(db.Boolean, nullable=False, default=True)
    muted = db.Column(db.Boolean, nullable=False, default=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    session_version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    last_login = db.Column(db.DateTime(timezone=True))

    @property
    def is_active(self):  # Flask-Login hook
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256:600000")  # PBKDF2 + per-user salt

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    from flask import session
    user = db.session.get(User, int(user_id))
    if not user or not user.active:
        return None
    expected = session.get("_auth_version")
    if expected is None:
        session["_auth_version"] = user.session_version
    elif int(expected) != user.session_version:
        session.clear()
        return None
    return user


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False, default="")
    file_key = db.Column(db.String(200))
    file_name = db.Column(db.String(255))
    file_mime = db.Column(db.String(100))
    channel = db.Column(db.String(20), nullable=False, default="general", server_default="general", index=True)
    deleted = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user = db.relationship("User")

    # The community is split into these rooms (key -> label shown on the tabs). Order = tab order.
    CHANNELS = {"nism": "NISM", "investors": "Investors", "traders": "Traders", "general": "General"}
    DEFAULT_CHANNEL = "general"

    def to_dict(self):
        from .storage import file_url

        d = {
            "id": self.id,
            "user_id": self.user_id,
            "user": self.user.name,
            "is_admin": self.user.is_admin,
            "body": self.body,
            "channel": self.channel or self.DEFAULT_CHANNEL,
            "created_at": _iso_utc(self.created_at),
            "file": None,
        }
        if self.file_key:
            is_image = (self.file_mime or "").startswith("image/")
            is_video = (self.file_mime or "").startswith("video/")
            d["file"] = {
                "name": self.file_name,
                "is_image": is_image,
                "is_video": is_video,
                "url": file_url(self.file_key, self.file_name, is_image or is_video),  # photos/videos open inline
            }
        return d


class Post(db.Model):
    """Admin 'opinions' / announcements, optionally with an attached file."""
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(20), nullable=False, default="news", server_default="news")  # news | info | post
    section = db.Column(db.String(20), nullable=False, default="home", server_default="home", index=True)  # home | news | mutual_funds | stocks
    pinned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    file_key = db.Column(db.String(200))
    file_name = db.Column(db.String(255))
    file_mime = db.Column(db.String(100))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    author = db.relationship("User")

    CATEGORIES = {"news": "📰 News", "info": "ℹ️ Information", "post": "📝 Post"}
    # Where a post is published: the home feed or one of the three section pages.
    SECTIONS = {"home": "🏠 Home feed", "news": "📰 News", "mutual_funds": "📊 Mutual Funds", "stocks": "📈 Stocks"}

    @property
    def section_label(self):
        return self.SECTIONS.get(self.section, self.SECTIONS["home"])

    @property
    def category_label(self):
        return self.CATEGORIES.get(self.category, self.CATEGORIES["post"])

    likes = db.relationship("PostLike", cascade="all, delete-orphan")

    @property
    def is_image(self):
        return (self.file_mime or "").startswith("image/")

    @property
    def is_video(self):
        return (self.file_mime or "").startswith("video/")

    @property
    def is_media(self):
        return self.is_image or self.is_video


class PostLike(db.Model):
    """One like per member per post (enforced by the database)."""
    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_like"),)
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Quiz(db.Model):
    __tablename__ = "quizzes"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    topic = db.Column(db.String(200))            # AI quizzes: what it was generated about
    difficulty = db.Column(db.String(10))        # easy / medium / hard (AI quizzes)
    source = db.Column(db.String(10), nullable=False, default="manual")  # "manual" or "ai"
    notified_at = db.Column(db.DateTime(timezone=True))  # set once members were e-mailed (never twice)
    questions = db.relationship(
        "Question", backref="quiz", cascade="all, delete-orphan", order_by="Question.id"
    )


class Question(db.Model):
    __tablename__ = "questions"
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False, index=True)
    text = db.Column(db.String(500), nullable=False)
    options = db.Column(db.JSON, nullable=False)  # list[str]
    correct_index = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.Text)  # shown on the result page (AI quizzes)


class QuizAttempt(db.Model):
    __tablename__ = "quiz_attempts"
    __table_args__ = (UniqueConstraint("quiz_id", "user_id", name="uq_attempt_once"),)
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    answers = db.Column(db.JSON, nullable=False)  # {question_id: chosen_index}
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    quiz = db.relationship("Quiz")
    user = db.relationship("User")


class Poll(db.Model):
    __tablename__ = "polls"
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(300), nullable=False)
    is_open = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    options = db.relationship(
        "PollOption", backref="poll", cascade="all, delete-orphan", order_by="PollOption.id"
    )


class PollOption(db.Model):
    __tablename__ = "poll_options"
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False, index=True)
    text = db.Column(db.String(200), nullable=False)


class PollVote(db.Model):
    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_vote_once"),)
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False, index=True)
    option_id = db.Column(db.Integer, db.ForeignKey("poll_options.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


class Setting(db.Model):
    """Small key/value table for admin-controlled switches (e.g. chat mode)."""
    __tablename__ = "settings"
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)
