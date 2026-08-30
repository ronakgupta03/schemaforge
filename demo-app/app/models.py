from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    profile: Mapped["UserProfile"] = relationship(
        uselist=False, back_populates="user", cascade="all, delete-orphan"
    )

    # Backward-compat API: address/date_of_birth live on user_profiles (1:1),
    # exposed here so existing call sites (tests, serializers) keep working.
    def __init__(self, *args, address: str | None = None,
                 date_of_birth: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if address is not None or date_of_birth is not None:
            if self.profile is None:
                self.profile = UserProfile()
            if address is not None:
                self.profile.address = address
            if date_of_birth is not None:
                self.profile.date_of_birth = date_of_birth

    @property
    def address(self) -> str:
        return self.profile.address if self.profile else ""

    @property
    def date_of_birth(self) -> str | None:
        return self.profile.date_of_birth if self.profile else None


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    user: Mapped["User"] = relationship(back_populates="profile")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column()
