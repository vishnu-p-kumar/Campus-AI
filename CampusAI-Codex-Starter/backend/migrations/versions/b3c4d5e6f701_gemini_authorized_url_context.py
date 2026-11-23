"""Use exact admin-authorized URLs with Gemini URL Context."""

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f701"
down_revision = "b7c9d2e4f103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authorized_source_urls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["authorized_source_domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_authorized_source_urls_domain_id", "authorized_source_urls", ["domain_id"])
    connection = op.get_bind()
    connection.execute(sa.text("""INSERT INTO authorized_source_urls (domain_id, url, added_by, created_at)
        SELECT id, 'https://' || domain || '/', added_by, created_at FROM authorized_source_domains"""))
    with op.batch_alter_table("placement_assistant_settings") as batch:
        batch.alter_column("web_search_enabled", new_column_name="url_context_enabled",
                           existing_type=sa.Boolean(), existing_nullable=False,
                           existing_server_default=sa.false())


def downgrade() -> None:
    with op.batch_alter_table("placement_assistant_settings") as batch:
        batch.alter_column("url_context_enabled", new_column_name="web_search_enabled",
                           existing_type=sa.Boolean(), existing_nullable=False,
                           existing_server_default=sa.false())
    op.drop_index("ix_authorized_source_urls_domain_id", table_name="authorized_source_urls")
    op.drop_table("authorized_source_urls")
