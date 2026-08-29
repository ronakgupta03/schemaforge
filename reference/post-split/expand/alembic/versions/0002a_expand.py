"""0002a expand: create user_profiles and backfill (additive only).

Zero-downtime phase 1. Safe to apply on a live database: creates a new table
and backfills it from users WITHOUT dropping or locking users for long. The
old columns (users.address, users.date_of_birth) remain in place so the
running application keeps serving.

Revision ID: 0002a
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002a"
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


def downgrade() -> None:
    op.drop_table("user_profiles")
