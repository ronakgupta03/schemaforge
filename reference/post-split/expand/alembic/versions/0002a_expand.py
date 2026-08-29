"""0002a expand: create user_profiles, backfill, and relax NOT NULL.

Zero-downtime phase 1. Safe to apply on a live database: creates a new table,
backfills it from users, and makes the legacy address column nullable — all
WITHOUT dropping or locking users for long. The old columns remain in place
so the running application keeps serving; making address nullable lets the
FINAL app build (which no longer writes users.address) insert rows during
the expand->contract window.

Scope: a one-shot INSERT..SELECT backfill is correct for a quiesced or
low-write window. Handling truly concurrent writes during the window requires
app-level dual-write coordination (the expand app build dual-writes; the
contract phase reconciles stragglers), which is the application's
responsibility, not the migration agent's.

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
    # Relax NOT NULL so the FINAL app build can insert users without address
    # during the expand->contract window. date_of_birth is already nullable.
    op.alter_column("users", "address", nullable=True)


def downgrade() -> None:
    op.drop_table("user_profiles")
    # Restore the original NOT NULL contract. Fails loudly if any row has a
    # NULL address (e.g. a user created by the final app during the expand
    # window), which is correct — such a rollback is unsafe to complete.
    op.alter_column("users", "address", nullable=False)
