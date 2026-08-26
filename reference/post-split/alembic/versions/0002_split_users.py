"""split users into users + user_profiles (1:1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Strategy: expand (create table) -> backfill (INSERT ... SELECT) -> contract
(drop moved columns). No window where a write to users can lose data; the
only lock moment is the final column drops (ACCESS EXCLUSIVE, brief).
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
    )
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users"
    )
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "address")


def downgrade() -> None:
    op.add_column("users", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.String(length=10), nullable=True))
    op.execute(
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
    op.alter_column("users", "address", nullable=False)
    op.drop_table("user_profiles")