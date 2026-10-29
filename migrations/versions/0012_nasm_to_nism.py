"""rename the NASM chat room to NISM (moves existing messages)"""
from alembic import op

revision = "0012_nasm_to_nism"
down_revision = "0011_market_updates"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE messages SET channel = 'nism' WHERE channel = 'nasm'")


def downgrade():
    op.execute("UPDATE messages SET channel = 'nasm' WHERE channel = 'nism'")
