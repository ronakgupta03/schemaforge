"""Seed the bookstore DB. Usage: DATABASE_URL=... python seed.py [users] [books]"""
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Book, User

users_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
books_n = int(sys.argv[2]) if len(sys.argv) > 2 else 3

engine = create_engine(os.environ["DATABASE_URL"])
Session = sessionmaker(bind=engine)

with Session() as s:
    if s.query(User).count() == 0:
        s.add_all(
            User(
                name=f"user{i}",
                email=f"user{i}@example.com",
                address=f"{i} Main St",
                date_of_birth="1990-01-01" if i % 2 == 0 else None,
            )
            for i in range(users_n)
        )
    if s.query(Book).count() == 0:
        s.add_all(
            Book(
                title=f"Book {i}",
                author=f"Author {i % 7}",
                price_cents=999 + i,
            )
            for i in range(books_n)
        )
    s.commit()

print(f"seeded: users={s.query(User).count()}, books={s.query(Book).count()}")
