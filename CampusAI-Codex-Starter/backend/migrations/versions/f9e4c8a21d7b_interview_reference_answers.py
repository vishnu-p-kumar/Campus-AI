"""Store the reference answer for the active typed interview question."""

from alembic import op
import sqlalchemy as sa


revision = "f9e4c8a21d7b"
down_revision = "c05d711c2284"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("current_reference_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_sessions", "current_reference_answer")
