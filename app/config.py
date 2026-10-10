import os
from datetime import timedelta


def _db_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_DB_URL = _db_url()
_REDIS = os.environ.get("REDIS_URL", "")


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    TRUSTED_HOSTS = [h.strip() for h in os.environ.get("TRUSTED_HOSTS", "").split(",") if h.strip()] or None

    # --- Database (SQLite locally, PostgreSQL/RDS in production) ---
    SQLALCHEMY_DATABASE_URI = _DB_URL
    SQLALCHEMY_ENGINE_OPTIONS = (
        {}
        if _DB_URL.startswith("sqlite")
        else {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_size": int(os.environ.get("DB_POOL_SIZE", 10)),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", 10)),
            # Never let a broken DB connection make login/registration appear
            # to hang forever. Production can override these values.
            "connect_args": {
                "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", 5)),
                "options": f"-c statement_timeout={int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', 15000))}",
            },
        }
    )

    # --- Redis: Socket.IO fan-out across servers + shared rate-limit counters ---
    REDIS_URL = _REDIS
    RATELIMIT_STORAGE_URI = _REDIS or "memory://"
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") == "1"  # set 0 ONLY on a staging copy for load tests

    # --- Sessions / cookies ---
    # Members are logged out automatically this many seconds after they log in (default 1 hour),
    # no matter how active they are. Override with SESSION_LIFETIME_SECONDS.
    SESSION_LIFETIME_SECONDS = int(os.environ.get("SESSION_LIFETIME_SECONDS", 3600))
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=SESSION_LIFETIME_SECONDS)
    SESSION_REFRESH_EACH_REQUEST = False  # absolute timeout: activity does not extend the session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
    SESSION_PROTECTION = "strong"
    SESSION_COOKIE_PATH = "/"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_PATH = "/"
    TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"  # 1 behind ALB/CloudFront

    # --- Uploads ---
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 15))   # photos, PDFs, Office files, ...
    MAX_VIDEO_MB = int(os.environ.get("MAX_VIDEO_MB", 50))     # videos (mp4)
    # Flask's hard request cap must fit the biggest allowed file (+1 MB for form overhead); the per-type limits
    # above are enforced in storage.limit_bytes().
    MAX_CONTENT_LENGTH = (max(MAX_UPLOAD_MB, MAX_VIDEO_MB) + 1) * 1024 * 1024
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.getcwd(), "uploads"))
    S3_BUCKET = os.environ.get("S3_BUCKET", "")  # empty -> store on local disk
    AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
    MAX_PASSWORD_LENGTH = int(os.environ.get("MAX_PASSWORD_LENGTH", 128))

    # Password reset / email. In AWS, use the ECS task IAM role with SES.
    EMAIL_VERIFY_TTL = int(os.environ.get("EMAIL_VERIFY_TTL", 86400))  # sign-up confirmation link lifetime (seconds)
    PASSWORD_RESET_TTL = int(os.environ.get("PASSWORD_RESET_TTL", 3600))
    PASSWORD_RESET_EMAIL_FROM = os.environ.get("PASSWORD_RESET_EMAIL_FROM", "")
    # Optional fixed public address used in e-mailed links (e.g. https://community.example.com).
    # Leave empty to build links from the address the member is visiting.
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
    # Outgoing mail (password reset + e-mail confirmation). Gmail: smtp.gmail.com / 587 / an App Password.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0") == "1"   # 1 for port 465; otherwise STARTTLS is used
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    EMAIL_ALLOWED_DOMAINS = os.environ.get("EMAIL_ALLOWED_DOMAINS", "")  # empty = Gmail only; * = any domain
    DEV_SHOW_RESET_LINK = os.environ.get("DEV_SHOW_RESET_LINK", "1") == "1" and APP_ENV != "production"
    # AI quiz generator (Google Gemini). The key lives ONLY in the environment/.env; blank = feature off.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", 45))   # seconds per request
    QUIZ_MAX_QUESTIONS = int(os.environ.get("QUIZ_MAX_QUESTIONS", 20))
    QUIZ_NOTIFY_EMAILS = os.environ.get("QUIZ_NOTIFY_EMAILS", "1") == "1"  # e-mail members when a quiz is published
    ADMIN_POST_EMAILS = os.environ.get("ADMIN_POST_EMAILS", "1") == "1"  # e-mail members when the admin posts/shares in the feed or community
    VIDEO_EXTENSIONS = {"mp4"}
    ALLOWED_EXTENSIONS = {
        "png", "jpg", "jpeg", "gif", "webp",
        "pdf", "txt", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "mp4",
    }
    IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    # --- Socket.IO ---
    SOCKETIO_ASYNC_MODE = os.environ.get("SOCKETIO_ASYNC_MODE") or None
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "")  # empty = same-origin only

    # --- Site ---
    WHATSAPP_COMMUNITY_LINK = os.environ.get(
        "WHATSAPP_COMMUNITY_LINK", "https://chat.whatsapp.com/your-community-invite-code"
    )
    SITE_NAME = os.environ.get("SITE_NAME", "Rakshith N Finance")
    CHAT_HISTORY_PAGE = 50
    MAX_MESSAGE_LEN = 2000
    CHAT_SLOW_SECONDS = int(os.environ.get("CHAT_SLOW_SECONDS", 15))   # "slow mode" gap per member
    SOCKET_MAX_BUFFER = int(os.environ.get("SOCKET_MAX_BUFFER", 65536))  # reject giant socket messages
    UPLOAD_TOKEN_MAX_AGE = 900  # seconds a direct-upload receipt stays valid
