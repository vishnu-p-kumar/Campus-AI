"""repair source document foreign key on placement requirements

Revision ID: c4d7a1f29b63
Revises: 7f49777a31ca
"""
from alembic import context, op
import sqlalchemy as sa


revision = "c4d7a1f29b63"
down_revision = "7f49777a31ca"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        # PostgreSQL base revisions did not create this FK. SQLite's base
        # migration created it inline because SQLite accepts forward refs.
        if op.get_context().dialect.name == "postgresql":
            op.create_foreign_key(
                "fk_requirement_document", "company_requirements", "documents",
                ["source_document_id"], ["id"],
            )
        return

    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_foreign_keys("company_requirements")
    present = any(
        item.get("referred_table") == "documents"
        and item.get("constrained_columns") == ["source_document_id"]
        for item in constraints
    )
    if not present:
        if op.get_context().dialect.name == "sqlite":
            with op.batch_alter_table("company_requirements") as batch_op:
                batch_op.create_foreign_key(
                    "fk_requirement_document", "documents", ["source_document_id"], ["id"]
                )
        else:
            op.create_foreign_key(
                "fk_requirement_document", "company_requirements", "documents",
                ["source_document_id"], ["id"],
            )


def downgrade() -> None:
    if context.is_offline_mode():
        if op.get_context().dialect.name == "postgresql":
            op.drop_constraint("fk_requirement_document", "company_requirements", type_="foreignkey")
        return

    inspector = sa.inspect(op.get_bind())
    present = any(
        item.get("name") == "fk_requirement_document"
        or (item.get("referred_table") == "documents" and item.get("constrained_columns") == ["source_document_id"])
        for item in inspector.get_foreign_keys("company_requirements")
    )
    if present:
        with op.batch_alter_table("company_requirements") as batch_op:
            batch_op.drop_constraint("fk_requirement_document", type_="foreignkey")
