"""feed categories and pinning for admin posts"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_post_feed_fields"
down_revision = "0003_profile_fields"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("posts")}
    if "category" not in columns:
        op.add_column("posts", sa.Column("category", sa.String(20), nullable=False, server_default="news"))
    if "pinned" not in columns:
        op.add_column("posts", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("posts")}
    if "pinned" in columns:
        op.drop_column("posts", "pinned")
    if "category" in columns:
        op.drop_column("posts", "category")
