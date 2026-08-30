"""split users into users + user_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

Expand -> backfill -> contract in a single transaction:
  1. CREATE TABLE user_profiles (id PK, user_id 1:1 FK, address, date_of_birth)
  2. INSERT ... SELECT backfill from users
  3. DROP COLUMN users.address, users.date_of_birth
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
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users"
    )
    op.drop_column("users", "address")
    op.drop_column("users", "date_of_birth")


def downgrade() -> None:
    # Orphan guard: never roll back while any user lacks a profile row —
    # dropping user_profiles without a full copy-back would silently lose
    # address data and burn the incident clock with a cryptic IntegrityError.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM users u WHERE NOT EXISTS "
        "(SELECT 1 FROM user_profiles p WHERE p.user_id = u.id)) THEN "
        "RAISE EXCEPTION 'rollback blocked: users exist without a user_profiles row'; "
        "END IF; END $$;"
    )
    op.add_column(
        "users",
        sa.Column("address", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
    )
    op.execute(
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
    op.alter_column("users", "address", server_default=None)
    op.drop_table("user_profiles")
