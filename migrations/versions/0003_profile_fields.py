"""add date of birth and occupation to users"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_profile_fields"
down_revision = "0002_session_version"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "dob" not in columns:
        op.add_column("users", sa.Column("dob", sa.Date(), nullable=True))
    if "occupation" not in columns:
        op.add_column("users", sa.Column("occupation", sa.String(100), nullable=True))


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "occupation" in columns:
        op.drop_column("users", "occupation")
    if "dob" in columns:
        op.drop_column("users", "dob")
