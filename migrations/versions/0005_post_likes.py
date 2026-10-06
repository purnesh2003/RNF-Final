"""likes on feed posts"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_post_likes"
down_revision = "0004_post_feed_fields"
branch_labels = None
depends_on = None


def upgrade():
    if inspect(op.get_bind()).has_table("post_likes"):
        return
    op.create_table(
        "post_likes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("post_id", "user_id", name="uq_post_like"),
    )
    op.create_index("ix_post_likes_post_id", "post_likes", ["post_id"])
    op.create_index("ix_post_likes_user_id", "post_likes", ["user_id"])


def downgrade():
    if inspect(op.get_bind()).has_table("post_likes"):
        op.drop_table("post_likes")
