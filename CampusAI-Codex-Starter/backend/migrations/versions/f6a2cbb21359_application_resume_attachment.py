"""Store a resume attachment for each placement application."""

from alembic import op
import sqlalchemy as sa


revision = "f6a2cbb21359"
down_revision = "b3c4d5e6f701"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("resume_filename", sa.String(length=255), nullable=True))
    op.add_column("applications", sa.Column("resume_storage_path", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "resume_storage_path")
    op.drop_column("applications", "resume_filename")
