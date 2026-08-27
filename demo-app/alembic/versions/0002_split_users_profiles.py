"""split users into users + user_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) EXPAND: create the 1:1 user_profiles table
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    # 2) BACKFILL: copy address/date_of_birth from users (single INSERT..SELECT)
    op.execute(
        """
        INSERT INTO user_profiles (user_id, address, date_of_birth)
        SELECT id, address, date_of_birth FROM users
        """
    )

    # data-preservation guard inside the same transaction: the split is only
    # valid if every user got exactly one profile
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM users) <> (SELECT count(*) FROM user_profiles) THEN
                RAISE EXCEPTION 'split parity check failed: user_profiles count <> users count';
            END IF;
            IF EXISTS (SELECT 1 FROM user_profiles GROUP BY user_id HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'split parity check failed: duplicate user_id in user_profiles';
            END IF;
        END $$;
        """
    )

    # 3) CONTRACT: users keeps id/name/email only
    op.drop_column("users", "address")
    op.drop_column("users", "date_of_birth")


def downgrade() -> None:
    # Reject rollback if any user has no user_profiles row: the join below
    # would leave address NULL and the NOT NULL alteration would fail
    # (fabricating a placeholder would silently corrupt data instead).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM users u
                LEFT JOIN user_profiles p ON p.user_id = u.id
                WHERE p.id IS NULL
            ) THEN
                RAISE EXCEPTION 'rollback blocked: users exist without a user_profiles row';
            END IF;
        END $$;
        """
    )
    op.add_column("users", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.String(length=10), nullable=True))
    op.execute(
        """
        UPDATE users u
        SET address = p.address,
            date_of_birth = p.date_of_birth
        FROM user_profiles p
        WHERE p.user_id = u.id
        """
    )
    op.alter_column("users", "address", nullable=False)
    op.drop_table("user_profiles")