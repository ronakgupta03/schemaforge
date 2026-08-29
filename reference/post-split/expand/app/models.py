"""Dual-write models for the expand window (zero-downtime phase 1).

The old columns (users.address, users.date_of_birth) still exist on the
table; the new user_profiles table is populated by the expand backfill and
by dual-writes from this app build. Reads stay on the old columns here for
simplicity — they are still present and correct. The FINAL models
(reference/post-split/app/models.py) move reads to user_profiles and drop
the old columns.
"""
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # KEPT during expand — the running app still reads these.
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    profile: Mapped["UserProfile"] = relationship(
        "UserProfile", uselist=False, back_populates="user"
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    user: Mapped["User"] = relationship("User", back_populates="profile")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column()
