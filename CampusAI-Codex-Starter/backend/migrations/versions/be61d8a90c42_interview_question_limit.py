"""Store the requested number of questions in each practice session.

Revision ID: be61d8a90c42
Revises: a95c0d31e7f2
"""
from alembic import op
import sqlalchemy as sa


revision = "be61d8a90c42"
down_revision = "a95c0d31e7f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("question_limit", sa.Integer(), server_default="5", nullable=False))


def downgrade() -> None:
    op.drop_column("interview_sessions", "question_limit")
