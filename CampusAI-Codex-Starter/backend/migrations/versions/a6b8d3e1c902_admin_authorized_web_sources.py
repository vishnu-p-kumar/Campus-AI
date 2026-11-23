"""Add admin-managed authorized source domains for placement web search."""

from alembic import op
import sqlalchemy as sa


revision = "a6b8d3e1c902"
down_revision = "f9e4c8a21d7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authorized_source_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("domain"),
    )
    op.create_index("ix_authorized_source_domains_domain", "authorized_source_domains", ["domain"], unique=True)
    op.create_table(
        "placement_assistant_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("web_search_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("placement_assistant_settings")
    op.drop_index("ix_authorized_source_domains_domain", table_name="authorized_source_domains")
    op.drop_table("authorized_source_domains")
