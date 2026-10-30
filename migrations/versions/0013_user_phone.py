"""users.phone: 10-digit Indian mobile number collected at sign-up"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0013_user_phone"
down_revision = "0012_nasm_to_nism"
branch_labels = None
depends_on = None


def upgrade():
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "phone" not in cols:
        op.add_column("users", sa.Column("phone", sa.String(15), nullable=True))


def downgrade():
    op.drop_column("users", "phone")
