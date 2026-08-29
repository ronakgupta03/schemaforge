"""0002b contract: drop the moved columns (gated, destructive).

Zero-downtime phase 2. Applied ONLY after the operator deploys the final app
code and the contract-gate confirms no live code reads users.address or
users.date_of_birth. The drops are brief AccessExclusive locks; safe because
nothing reads the columns anymore.

Revision ID: 0002b
Revises: 0002a
"""
from alembic import op
import sqlalchemy as sa

revision = "0002b"
down_revision = "0002a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reconcile: backfill user_profiles for any users created/updated after the
    # expand backfill (e.g. by the old app before the final app deploy) that
    # still lack a profile row. This closes most of the expand->contract gap;
    # truly concurrent writes during the drops themselves need app dual-write
    # or a brief cutover quiesce, which is out of scope for this agent.
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users u "
        "WHERE NOT EXISTS (SELECT 1 FROM user_profiles p WHERE p.user_id = u.id)"
    )
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "address")


def downgrade() -> None:
    # Re-add the columns from user_profiles. Guarded: if any user lacks a
    # profile row, rollback is blocked rather than fabricating NULLs that
    # would violate NOT NULL on re-add (same edge Qodo caught on PR #15).
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
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
    op.alter_column("users", "address", nullable=False)
