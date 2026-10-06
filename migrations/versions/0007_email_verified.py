"""track whether a member has confirmed their e-mail address"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007_email_verified"
down_revision = "0006_post_sections"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "email_verified" not in columns:
        # existing members count as verified; only new sign-ups are asked to confirm
        op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "email_verified" in columns:
        op.drop_column("users", "email_verified")
