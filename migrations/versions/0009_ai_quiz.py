"""AI quizzes: topic/difficulty/source/notified_at on quizzes, explanation on questions"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009_ai_quiz"
down_revision = "0008_message_channel"
branch_labels = None
depends_on = None


def _cols(table):
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    quiz = _cols("quizzes")
    if "topic" not in quiz:
        op.add_column("quizzes", sa.Column("topic", sa.String(200)))
    if "difficulty" not in quiz:
        op.add_column("quizzes", sa.Column("difficulty", sa.String(10)))
    if "source" not in quiz:
        # quizzes created before this release were typed in by hand
        op.add_column("quizzes", sa.Column("source", sa.String(10), nullable=False, server_default="manual"))
    if "notified_at" not in quiz:
        op.add_column("quizzes", sa.Column("notified_at", sa.DateTime(timezone=True)))
        # old quizzes must never trigger a mail-out
        op.execute("UPDATE quizzes SET notified_at = created_at")
    if "explanation" not in _cols("questions"):
        op.add_column("questions", sa.Column("explanation", sa.Text))


def downgrade():
    if "explanation" in _cols("questions"):
        op.drop_column("questions", "explanation")
    for name in ("notified_at", "source", "difficulty", "topic"):
        if name in _cols("quizzes"):
            op.drop_column("quizzes", name)
