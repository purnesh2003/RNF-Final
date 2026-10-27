"""market_updates table (AI pre-market / post-market briefings)"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011_market_updates"
down_revision = "0010_referral_schedule"
branch_labels = None
depends_on = None


def upgrade():
    if inspect(op.get_bind()).has_table("market_updates"):
        return
    op.create_table(
        "market_updates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("for_date", sa.Date, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("model", sa.String(60)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "for_date", name="uq_market_update_day"),
    )
    op.create_index("ix_market_updates_kind", "market_updates", ["kind"])
    op.create_index("ix_market_updates_for_date", "market_updates", ["for_date"])
    op.create_index("ix_market_updates_created_at", "market_updates", ["created_at"])


def downgrade():
    pass
