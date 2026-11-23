"""Add multiple-choice interview sessions and longer role specifications.

Revision ID: a95c0d31e7f2
Revises: c742e8c14b31
"""
from alembic import op
import sqlalchemy as sa


revision = "a95c0d31e7f2"
down_revision = "c742e8c14b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch:
        batch.alter_column("focus", existing_type=sa.String(length=240), type_=sa.Text(), existing_nullable=True)
        batch.add_column(sa.Column("question_type", sa.String(length=24), server_default="typed", nullable=False))
        batch.add_column(sa.Column("current_options", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("current_correct_answer", sa.String(length=1), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch:
        batch.drop_column("current_correct_answer")
        batch.drop_column("current_options")
        batch.drop_column("question_type")
        batch.alter_column("focus", existing_type=sa.Text(), type_=sa.String(length=240), existing_nullable=True)
