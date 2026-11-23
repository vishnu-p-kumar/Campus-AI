"""Persist structured Gemini resume and skill guidance.

Revision ID: c742e8c14b31
Revises: a86df5b2c193
"""
from alembic import op
import sqlalchemy as sa


revision = "c742e8c14b31"
down_revision = "a86df5b2c193"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_analyses", sa.Column("ai_review", sa.JSON(), nullable=True))
    op.add_column("skill_gap_analyses", sa.Column("ai_guidance", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_gap_analyses", "ai_guidance")
    op.drop_column("resume_analyses", "ai_review")
