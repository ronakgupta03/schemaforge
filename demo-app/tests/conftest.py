import os

# Force the app onto the test database BEFORE app is imported (db.py reads env).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5434/bookstore_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Base, User, UserProfile  # noqa: E402


@pytest.fixture(scope="session")
def client():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        if not s.query(User).first():
            s.add_all(
                [
                    User(name="Ada", email="ada@example.com",
                         profile=UserProfile(address="1 Main St", date_of_birth="1990-01-01")),
                    User(name="Bob", email="bob@example.com",
                         profile=UserProfile(address="2 Side St")),
                ]
            )
            s.commit()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
    engine.dispose()
