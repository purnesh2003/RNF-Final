"""invalidate sessions when credentials are changed"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_session_version"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "session_version" not in columns:
        op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))

def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "session_version" in columns:
        op.drop_column("users", "session_version")
