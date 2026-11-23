"""Remove the redundant index covered by the domain unique constraint."""

from alembic import op


revision = "b7c9d2e4f103"
down_revision = "a6b8d3e1c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_authorized_source_domains_domain", table_name="authorized_source_domains")


def downgrade() -> None:
    op.create_index("ix_authorized_source_domains_domain", "authorized_source_domains", ["domain"], unique=True)
