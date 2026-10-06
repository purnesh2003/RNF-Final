"""baseline current community schema"""
from alembic import op
from sqlalchemy import inspect
from flask import current_app

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    inspector = inspect(op.get_bind())
    if not inspector.has_table("users"):
        current_app.extensions["migrate"].db.metadata.create_all(bind=op.get_bind())

def downgrade():
    # Baseline migrations are intentionally irreversible in production.
    pass
