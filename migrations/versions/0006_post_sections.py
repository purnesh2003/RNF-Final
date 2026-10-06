"""publish posts to the home feed or to the News / Mutual Funds / Stocks sections"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_post_sections"
down_revision = "0005_post_likes"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("posts")}
    if "section" not in columns:
        op.add_column("posts", sa.Column("section", sa.String(20), nullable=False, server_default="home"))
        op.create_index("ix_posts_section", "posts", ["section"])


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("posts")}
    if "section" in columns:
        op.drop_index("ix_posts_section", table_name="posts")
        op.drop_column("posts", "section")
