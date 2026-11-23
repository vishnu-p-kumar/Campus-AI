"""add durable document ingestion jobs"""
from alembic import op
import sqlalchemy as sa

revision = "b4810c2e6d91"
down_revision = "f25a7d931bc4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Repairs databases created while the preceding auth bucket index was absent.
    op.create_index("ix_auth_rate_limit_bucket_window", "auth_rate_limit_buckets", ["window_start"], if_not_exists=True)
    op.add_column("documents", sa.Column("ingestion_status", sa.String(length=24), server_default="completed", nullable=False))
    op.add_column("documents", sa.Column("ingestion_error", sa.String(length=300), nullable=True))
    op.create_index("ix_documents_ingestion_status", "documents", ["ingestion_status"])
    op.create_table(
        "document_ingestion_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.LargeBinary(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_ingestion_jobs_status", "document_ingestion_jobs", ["status"])
    op.create_index("ix_document_ingestion_jobs_ready", "document_ingestion_jobs", ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_document_ingestion_jobs_ready", table_name="document_ingestion_jobs")
    op.drop_index("ix_document_ingestion_jobs_status", table_name="document_ingestion_jobs")
    op.drop_table("document_ingestion_jobs")
    op.drop_index("ix_documents_ingestion_status", table_name="documents")
    op.drop_column("documents", "ingestion_error")
    op.drop_column("documents", "ingestion_status")
    op.drop_index("ix_auth_rate_limit_bucket_window", table_name="auth_rate_limit_buckets", if_exists=True)
