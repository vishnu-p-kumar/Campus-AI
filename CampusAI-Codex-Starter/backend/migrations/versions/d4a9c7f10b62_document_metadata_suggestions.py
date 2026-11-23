"""store extracted document metadata suggestions"""
from alembic import op
import sqlalchemy as sa

revision = "d4a9c7f10b62"
down_revision = "b4810c2e6d91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("suggested_category", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("classification_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("metadata_candidates", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("documents", "metadata_candidates")
    op.drop_column("documents", "classification_score")
    op.drop_column("documents", "suggested_category")
