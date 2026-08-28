"""split users into users + user_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

Expand -> backfill -> contract. Zero-downtime: the old columns stay
writable until the very last ALTER in the same transaction; the app is
the only writer and is updated in the same PR.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. expand
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )
    # 2. backfill (single statement, ~O(n), 200k rows on prod)
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users"
    )
    # 3. contract
    op.drop_column("users", "address")
    op.drop_column("users", "date_of_birth")


def downgrade() -> None:
    # re-add nullable, copy back, guard, then set NOT NULL
    op.add_column("users", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.String(length=10), nullable=True))
    op.execute(
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
    # orphan-guard: a rollback on partial data must fail loudly, not silently
    # produce NULL addresses (or die with a cryptic IntegrityError at SET NOT NULL)
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM users u WHERE NOT EXISTS
                       (SELECT 1 FROM user_profiles p WHERE p.user_id = u.id)) THEN
                RAISE EXCEPTION 'rollback blocked: users exist without a user_profiles row';
            END IF;
        END $$;"""
    )
    op.execute("ALTER TABLE users ALTER COLUMN address SET NOT NULL")
    op.drop_table("user_profiles")
