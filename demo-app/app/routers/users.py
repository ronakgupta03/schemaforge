from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..db import SessionLocal
from ..models import User, UserProfile

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    name: str
    email: str
    address: str
    date_of_birth: str | None = None


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    address: str
    date_of_birth: str | None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_out(user: User) -> UserOut:
    p = user.profile
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        address=p.address if p is not None else "",
        date_of_birth=p.date_of_birth if p is not None else None,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    users = (
        db.query(User)
        .options(joinedload(User.profile))
        .order_by(User.id)
        .all()
    )
    return [to_out(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id, options=[joinedload(User.profile)])
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return to_out(user)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    user = User(name=payload.name, email=payload.email)
    user.profile = UserProfile(
        address=payload.address, date_of_birth=payload.date_of_birth
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return to_out(user)
