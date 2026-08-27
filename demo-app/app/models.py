from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)

    # 1:1 profile split (user_profiles holds address/date_of_birth).
    # lazy="selectin" keeps list_users a constant number of queries.
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # Association proxies keep the ORM surface (and the /users API contract)
    # unchanged: User(address=..., date_of_birth=...) writes through to the profile.
    address: Mapped[str] = association_proxy(
        "profile", "address", creator=lambda v: UserProfile(address=v)
    )
    date_of_birth: Mapped[str | None] = association_proxy(
        "profile", "date_of_birth", creator=lambda v: UserProfile(date_of_birth=v)
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column()