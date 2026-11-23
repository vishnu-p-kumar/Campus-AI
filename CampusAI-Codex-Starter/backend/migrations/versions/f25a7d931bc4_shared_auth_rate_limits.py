"""add shared database-backed authentication rate limit buckets

Revision ID: f25a7d931bc4
Revises: e1b3c6d4a902
"""
from alembic import op
import sqlalchemy as sa


revision = "f25a7d931bc4"
down_revision = "e1b3c6d4a902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("rate_key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("rate_key", "window_start"),
    )
    op.create_index("ix_auth_rate_limit_bucket_window", "auth_rate_limit_buckets", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limit_bucket_window", table_name="auth_rate_limit_buckets")
    op.drop_table("auth_rate_limit_buckets")
