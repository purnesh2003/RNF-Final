"""Public home page, health checks, private file serving, and member-facing
opinions / quizzes / polls."""
import os
import secrets
from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import csrf, db, limiter
from .models import Message, Poll, PollOption, PollVote, Post, PostLike, Quiz, QuizAttempt, User, is_future, post_is_live, quiz_is_live
from .mailer import external_link
from .storage import KEY_RE, file_url

bp = Blueprint("main", __name__)


def _feed_meta(posts):
    """Like counts per post and the set of post ids the current member liked (2 queries for the whole page)."""
    ids = [p.id for p in posts]
    counts, liked = {}, set()
    if ids:
        counts = dict(db.session.query(PostLike.post_id, func.count(PostLike.id))
                      .filter(PostLike.post_id.in_(ids)).group_by(PostLike.post_id).all())
        if current_user.is_authenticated:
            liked = {r[0] for r in db.session.query(PostLike.post_id)
                     .filter(PostLike.post_id.in_(ids), PostLike.user_id == current_user.id)}
    return counts, liked


@bp.route("/posts/<int:post_id>/like", methods=["POST"])
@login_required
@limiter.limit("60 per minute")
def like_post(post_id):
    post = db.get_or_404(Post, post_id)
    if is_future(post.created_at):  # still scheduled
        abort(404)
    existing = PostLike.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(PostLike(post_id=post.id, user_id=current_user.id))
        liked = True
    try:
        db.session.commit()
    except IntegrityError:  # double-tap race: the like already exists
        db.session.rollback()
        liked = True
    return jsonify(liked=liked, count=PostLike.query.filter_by(post_id=post.id).count())


@bp.route("/")
def home():
    page = request.args.get("page", 1, type=int)
    posts = Post.query.filter_by(section="home").filter(post_is_live()).order_by(Post.pinned.desc(), Post.created_at.desc()).paginate(
        page=page, per_page=8, error_out=False)
    likes, liked = _feed_meta(posts.items)
    # newest headline of the News / Mutual Funds cards
    latest = {k: Post.query.filter_by(section=k).filter(post_is_live()).order_by(Post.created_at.desc()).first()
              for k in ("news", "mutual_funds")}
    # the Quiz card: newest open quiz and (for members) whether they already took it
    latest_quiz = quiz_attempt = None
    if current_user.is_authenticated:
        latest_quiz = Quiz.query.filter_by(is_open=True).filter(quiz_is_live()).order_by(Quiz.created_at.desc(), Quiz.id.desc()).first()
        if latest_quiz:
            quiz_attempt = QuizAttempt.query.filter_by(quiz_id=latest_quiz.id, user_id=current_user.id).first()
    return render_template("home.html", posts=posts, file_url=file_url, likes=likes, liked=liked, latest=latest,
                           latest_quiz=latest_quiz, quiz_attempt=quiz_attempt)


@bp.route("/disclaimer")
def disclaimer():
    """Public disclaimer page (linked from the footer, the top bar and the sign-up form)."""
    return render_template("disclaimer.html")


@bp.route("/calculator")
def calculator():
    """Public calculator page with SIP and SWP tabs. All maths runs in the browser; nothing is stored."""
    return render_template("calculator.html")


@bp.route("/sip-calculator")
def sip_calculator():  # old address: kept so bookmarks and links keep working
    return redirect(url_for("main.calculator") + "#sip")


@bp.route("/swp-calculator")
def swp_calculator():
    return redirect(url_for("main.calculator") + "#swp")


@bp.route("/healthz")
@csrf.exempt
def healthz():  # load-balancer liveness check: no DB call so a DB blip doesn't kill every server
    return jsonify(status="ok")


@bp.route("/readyz")
@csrf.exempt
def readyz():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ready")
    except Exception:
        return jsonify(status="db-unavailable"), 503


@bp.route("/files/<key>")
def serve_file(key):
    """Local-disk mode only. In S3 mode URLs point straight at S3 (presigned).
    Photos/videos attached to public feed posts are viewable by visitors; everything else needs a login."""
    if current_app.config["S3_BUCKET"] or not KEY_RE.match(key):
        abort(404)
    ext = key.rsplit(".", 1)[-1]
    inline = ext in current_app.config["IMAGE_EXTENSIONS"] or ext in ("mp4", "pdf")  # PDFs open in the browser tab
    if not current_user.is_authenticated:
        public = ext != "pdf" and inline and Post.query.filter_by(file_key=key).filter(post_is_live()).first() is not None
        if not public:
            return current_app.login_manager.unauthorized()
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], key, as_attachment=not inline)


# ---------------------------------------------------------------- News / Mutual Funds / Stocks
SECTION_PAGES = {
    "news": ("News", "📰", "Latest market news and headlines, posted by Rakshith."),
    "mutual_funds": ("Mutual Funds", "📊", "Mutual fund updates posted by Rakshith."),
    "stocks": ("Stocks", "📈", "Stock ideas, market moves and analysis, posted by Rakshith."),
}


def _section_view(section):
    title, icon, blurb = SECTION_PAGES[section]
    page = request.args.get("page", 1, type=int)
    posts = Post.query.filter_by(section=section).filter(post_is_live()).order_by(Post.pinned.desc(), Post.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False)
    likes, liked = _feed_meta(posts.items)
    return render_template("section.html", posts=posts, file_url=file_url, likes=likes, liked=liked,
                           section=section, title=title, icon=icon, blurb=blurb)


@bp.route("/news")
@login_required
def news():
    return _section_view("news")


@bp.route("/mutual-funds")
@login_required
def mutual_funds():
    return _section_view("mutual_funds")


@bp.route("/stocks")
@login_required
def stocks():
    return _section_view("stocks")


SECTION_ENDPOINTS = {"home": "main.home", "news": "main.news", "mutual_funds": "main.mutual_funds", "stocks": "main.stocks"}


# ---------------------------------------------------------------- documents (every upload in one place)
DOC_TYPES = {"all": "All", "images": "Photos", "videos": "Videos", "files": "Documents"}
DOC_SOURCES = {"all": "Everywhere", "posts": "Admin posts",
               **{f"chat-{k}": f"{v} chat" for k, v in Message.CHANNELS.items()}}


def _type_filter(col, kind):
    if kind == "images":
        return col.like("image/%")
    if kind == "videos":
        return col.like("video/%")
    if kind == "files":
        return ~(col.like("image/%") | col.like("video/%"))
    return None


@bp.route("/documents")
@login_required
def documents():
    """One library of every file uploaded to the site - admin posts and community chat - newest first."""
    kind = request.args.get("type", "all")
    source = request.args.get("source", "all")
    kind = kind if kind in DOC_TYPES else "all"
    source = source if source in DOC_SOURCES else "all"
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    per_page = 24

    pq = Post.query.filter(Post.file_key.isnot(None), post_is_live())
    mq = Message.query.filter(Message.file_key.isnot(None), Message.deleted.is_(False))
    if _type_filter(Post.file_mime, kind) is not None:
        pq, mq = pq.filter(_type_filter(Post.file_mime, kind)), mq.filter(_type_filter(Message.file_mime, kind))
    if source == "posts":
        mq = None
    elif source.startswith("chat-"):
        pq, mq = None, mq.filter(Message.channel == source[5:])

    total = (pq.count() if pq is not None else 0) + (mq.count() if mq is not None else 0)
    rows = []
    take = page * per_page  # newest N from each source, merged, then cut to this page
    if pq is not None:
        rows += [("post", p) for p in pq.order_by(Post.created_at.desc()).limit(take)]
    if mq is not None:
        rows += [("chat", m) for m in mq.order_by(Message.created_at.desc()).limit(take)]
    rows.sort(key=lambda r: r[1].created_at, reverse=True)

    items = []
    for src, obj in rows[(page - 1) * per_page: page * per_page]:
        mime = obj.file_mime or ""
        is_image, is_video = mime.startswith("image/"), mime.startswith("video/")
        if src == "post":
            where, who, title = f"Admin post · {obj.section_label.split(' ', 1)[-1]}", obj.author.name, obj.title
        else:
            where = f"{Message.CHANNELS.get(obj.channel, 'General')} chat"
            who, title = obj.user.name, (obj.body or "")[:80]
        items.append({"name": obj.file_name or obj.file_key, "url": file_url(obj.file_key, obj.file_name, is_image or is_video),
                      "is_image": is_image, "is_video": is_video, "ext": obj.file_key.rsplit(".", 1)[-1].upper(),
                      "where": where, "who": who, "title": title, "created_at": obj.created_at})
    pages = max((total + per_page - 1) // per_page, 1)
    return render_template("documents.html", items=items, total=total, page=page, pages=pages,
                           kind=kind, source=source, types=DOC_TYPES, sources=DOC_SOURCES)


# ---------------------------------------------------------------- opinions
@bp.route("/opinions")
@login_required
def opinions():
    page = request.args.get("page", 1, type=int)
    posts = Post.query.filter(post_is_live()).order_by(Post.pinned.desc(), Post.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False)
    likes, liked = _feed_meta(posts.items)
    return render_template("feed.html", posts=posts, file_url=file_url, likes=likes, liked=liked)


# ---------------------------------------------------------------- quizzes
@bp.route("/quizzes")
@login_required
def quizzes():
    quizzes = Quiz.query.filter(quiz_is_live()).order_by(Quiz.created_at.desc()).all()
    done = {a.quiz_id: a for a in QuizAttempt.query.filter_by(user_id=current_user.id)}
    return render_template("quizzes.html", quizzes=quizzes, done=done)


@bp.route("/quizzes/<int:quiz_id>", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per hour", methods=["POST"])
def take_quiz(quiz_id):
    quiz = db.get_or_404(Quiz, quiz_id)
    if is_future(quiz.created_at):  # scheduled for later: not available yet
        abort(404)
    attempt = QuizAttempt.query.filter_by(quiz_id=quiz.id, user_id=current_user.id).first()
    if attempt:
        return render_template("quiz_result.html", quiz=quiz, attempt=attempt)
    if not quiz.is_open:
        flash("This quiz is closed.", "warning")
        return redirect(url_for("main.quizzes"))
    if request.method == "POST":
        answers, score = {}, 0
        for q in quiz.questions:
            raw = request.form.get(f"q{q.id}")
            choice = int(raw) if raw is not None and raw.isdigit() and int(raw) < len(q.options) else None
            answers[str(q.id)] = choice
            score += choice == q.correct_index
        attempt = QuizAttempt(quiz_id=quiz.id, user_id=current_user.id, score=score,
                              total=len(quiz.questions), answers=answers)
        db.session.add(attempt)
        try:
            db.session.commit()
        except IntegrityError:  # double-submit: keep the first attempt
            db.session.rollback()
            attempt = QuizAttempt.query.filter_by(quiz_id=quiz.id, user_id=current_user.id).first()
        return render_template("quiz_result.html", quiz=quiz, attempt=attempt)
    return render_template("quiz_take.html", quiz=quiz)


# ---------------------------------------------------------------- polls
def _poll_results(poll_ids):
    rows = (
        db.session.query(PollVote.poll_id, PollVote.option_id, func.count())
        .filter(PollVote.poll_id.in_(poll_ids))
        .group_by(PollVote.poll_id, PollVote.option_id)
        .all()
    )
    return {(p, o): c for p, o, c in rows}


@bp.route("/polls")
@login_required
def polls():
    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    counts = _poll_results([p.id for p in polls]) if polls else {}
    mine = {v.poll_id: v.option_id for v in PollVote.query.filter_by(user_id=current_user.id)}
    return render_template("polls.html", polls=polls, counts=counts, mine=mine)


@bp.route("/polls/<int:poll_id>/vote", methods=["POST"])
@login_required
@limiter.limit("30 per minute", methods=["POST"])
def vote(poll_id):
    poll = db.get_or_404(Poll, poll_id)
    opt_id = request.form.get("option", type=int)
    option = db.session.get(PollOption, opt_id) if opt_id else None
    if not poll.is_open:
        flash("This poll is closed.", "warning")
    elif not option or option.poll_id != poll.id:
        flash("Please pick an option.", "warning")
    else:
        db.session.add(PollVote(poll_id=poll.id, option_id=option.id, user_id=current_user.id))
        try:
            db.session.commit()
            flash("Vote recorded.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("You have already voted in this poll.", "info")
    return redirect(url_for("main.polls") + f"#poll-{poll.id}")


# ---------------------------------------------------------------- invite friends (referral link)
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes (0/O, 1/I)


def _referral_code(user):
    """The member's personal invite code; created the first time it is needed."""
    if not user.referral_code:
        for _ in range(10):
            code = "".join(secrets.choice(_CODE_CHARS) for _ in range(8))
            if not User.query.filter_by(referral_code=code).first():
                user.referral_code = code
                try:
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
    return user.referral_code


@bp.route("/invite")
@login_required
def invite():
    code = _referral_code(current_user)
    link = external_link("auth.register", ref=code)
    joined = User.query.filter_by(referred_by_id=current_user.id, email_verified=True).order_by(User.created_at.desc()).all()
    waiting = User.query.filter_by(referred_by_id=current_user.id, email_verified=False).count()
    site = current_app.config["SITE_NAME"]
    share = quote(f"Join me on {site}: news, mutual funds and stocks explained for learning, and a friendly community. Sign up here: {link}")
    return render_template("invite.html", link=link, code=code, joined=joined, waiting=waiting, share=share)


# ---------------------------------------------------------------- market updates (buttons in the community chat)
@bp.route("/market-update/<kind>")
@login_required
@limiter.limit("60 per minute")
def market_update(kind):
    """The latest saved pre-market / post-market briefing. Read-only: this never calls the AI."""
    from . import market_update as mu
    from .scheduler import to_local
    if kind not in mu.KINDS:
        abort(404)
    row = mu.latest(kind)
    if row is None:
        return jsonify(ok=False, label=mu.KINDS[kind],
                       error="The first update has not been published yet. Please check back soon."), 404
    return jsonify(ok=True, label=mu.KINDS[kind], body=row.body, sources=row.sources or [],
                   for_date=row.for_date.isoformat(), is_today=row.for_date == mu.today_local(),
                   updated=to_local(row.created_at).isoformat())
