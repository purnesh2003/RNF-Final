"""split the community chat into channels (NISM, Investors, Traders, General)"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008_message_channel"
down_revision = "0007_email_verified"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("messages")}
    if "channel" not in columns:
        # messages written before channels existed land in General
        op.add_column("messages", sa.Column("channel", sa.String(20), nullable=False, server_default="general"))
        op.create_index("ix_messages_channel", "messages", ["channel"])


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("messages")}
    if "channel" in columns:
        op.drop_index("ix_messages_channel", table_name="messages")
        op.drop_column("messages", "channel")
