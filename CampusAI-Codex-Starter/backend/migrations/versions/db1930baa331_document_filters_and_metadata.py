"""Add document company and academic year filters.

Revision ID: db1930baa331
Revises: 21097419382f
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "db1930baa331"
down_revision = "21097419382f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("academic_year", sa.String(length=20), nullable=True))
        batch_op.create_foreign_key("fk_documents_company_id_companies", "companies", ["company_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_documents_academic_year", ["academic_year"], unique=False)
        batch_op.create_index("ix_documents_company_id", ["company_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_company_id")
        batch_op.drop_index("ix_documents_academic_year")
        batch_op.drop_constraint("fk_documents_company_id_companies", type_="foreignkey")
        batch_op.drop_column("academic_year")
        batch_op.drop_column("company_id")
