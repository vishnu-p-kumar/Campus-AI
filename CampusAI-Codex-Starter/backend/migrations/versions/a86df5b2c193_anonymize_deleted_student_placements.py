"""preserve placement outcomes without retaining deleted student identity

Revision ID: a86df5b2c193
Revises: d4a9c7f10b62
Create Date: 2026-11-20
"""
from alembic import context, op
import sqlalchemy as sa


revision = "a86df5b2c193"
down_revision = "d4a9c7f10b62"
branch_labels = None
depends_on = None

FK_NAME = "fk_placement_records_student_user_id_users"
FK_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("placement_records", naming_convention=FK_NAMING) as batch:
            batch.drop_constraint(FK_NAME, type_="foreignkey")
            batch.alter_column("student_user_id", existing_type=sa.Integer(), nullable=True)
            batch.create_foreign_key(FK_NAME, "users", ["student_user_id"], ["id"], ondelete="SET NULL")
    else:
        if context.is_offline_mode():
            name = "placement_records_student_user_id_fkey"
        else:
            foreign_keys = sa.inspect(bind).get_foreign_keys("placement_records")
            name = next(item["name"] for item in foreign_keys if item["constrained_columns"] == ["student_user_id"])
        op.drop_constraint(name, "placement_records", type_="foreignkey")
        op.alter_column("placement_records", "student_user_id", existing_type=sa.Integer(), nullable=True)
        op.create_foreign_key(FK_NAME, "placement_records", "users", ["student_user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode() and bind.execute(sa.text("SELECT 1 FROM placement_records WHERE student_user_id IS NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while de-identified placement records exist; restore student IDs first.")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("placement_records", naming_convention=FK_NAMING) as batch:
            batch.drop_constraint(FK_NAME, type_="foreignkey")
            batch.alter_column("student_user_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(FK_NAME, "users", ["student_user_id"], ["id"], ondelete="CASCADE")
    else:
        op.drop_constraint(FK_NAME, "placement_records", type_="foreignkey")
        op.alter_column("placement_records", "student_user_id", existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(FK_NAME, "placement_records", "users", ["student_user_id"], ["id"], ondelete="CASCADE")
