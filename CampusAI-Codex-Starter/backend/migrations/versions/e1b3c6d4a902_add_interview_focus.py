"""add optional role focus to interview sessions

Revision ID: e1b3c6d4a902
Revises: c4d7a1f29b63
"""
from alembic import op
import sqlalchemy as sa


revision = "e1b3c6d4a902"
down_revision = "c4d7a1f29b63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("focus", sa.String(length=240), nullable=True))
    op.add_column("interview_sessions", sa.Column("current_question", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_sessions", "current_question")
    op.drop_column("interview_sessions", "focus")
