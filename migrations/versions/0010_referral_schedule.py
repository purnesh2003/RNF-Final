"""Referral links (users.referral_code / referred_by_id) and scheduled posts / quizzes (publish_at, notified_at)"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010_referral_schedule"
down_revision = "0009_ai_quiz"
branch_labels = None
depends_on = None


def _cols(table):
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {i["name"] for i in inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    users = _cols("users")
    if "referral_code" not in users:
        op.add_column("users", sa.Column("referral_code", sa.String(12)))
    if "referred_by_id" not in users:
        op.add_column("users", sa.Column("referred_by_id", sa.Integer))
    idx = _indexes("users")
    if "ix_users_referral_code" not in idx:
        op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    if "ix_users_referred_by_id" not in idx:
        op.create_index("ix_users_referred_by_id", "users", ["referred_by_id"])
    posts = _cols("posts")
    if "publish_at" not in posts:
        op.add_column("posts", sa.Column("publish_at", sa.DateTime(timezone=True)))
    if "notified_at" not in posts:
        op.add_column("posts", sa.Column("notified_at", sa.DateTime(timezone=True)))
    if "publish_at" not in _cols("quizzes"):
        op.add_column("quizzes", sa.Column("publish_at", sa.DateTime(timezone=True)))


def downgrade():
    pass
