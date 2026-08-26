"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("books")
    op.drop_table("users")
