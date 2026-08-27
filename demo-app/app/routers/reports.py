from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal

router = APIRouter(prefix="/reports", tags=["reports"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/addresses")
def user_addresses(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT u.name, u.address FROM users u ORDER BY u.id LIMIT 20")
    ).fetchall()
    return [{"name": r.name, "address": r.address} for r in rows]
