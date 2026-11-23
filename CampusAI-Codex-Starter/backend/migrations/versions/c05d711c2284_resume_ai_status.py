"""Persist AI review availability for resumes and role comparisons.

Revision ID: c05d711c2284
Revises: be61d8a90c42
"""
from alembic import op
import sqlalchemy as sa


revision = "c05d711c2284"
down_revision = "be61d8a90c42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_analyses", sa.Column("ai_status", sa.String(length=24), nullable=True))
    op.add_column("skill_gap_analyses", sa.Column("ai_status", sa.String(length=24), nullable=True))
    op.execute("UPDATE resume_analyses SET ai_status = CASE WHEN ai_review IS NOT NULL THEN 'complete' ELSE 'unavailable' END")
    op.execute("UPDATE skill_gap_analyses SET ai_status = CASE WHEN ai_guidance IS NOT NULL THEN 'complete' ELSE 'unavailable' END")
    with op.batch_alter_table("resume_analyses") as batch:
        batch.alter_column("ai_status", existing_type=sa.String(length=24), nullable=False, server_default="not_configured")
    with op.batch_alter_table("skill_gap_analyses") as batch:
        batch.alter_column("ai_status", existing_type=sa.String(length=24), nullable=False, server_default="not_configured")


def downgrade() -> None:
    with op.batch_alter_table("skill_gap_analyses") as batch:
        batch.drop_column("ai_status")
    with op.batch_alter_table("resume_analyses") as batch:
        batch.drop_column("ai_status")
