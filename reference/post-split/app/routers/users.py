from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

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


def to_out(user: User, profile: UserProfile) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        address=profile.address,
        date_of_birth=profile.date_of_birth,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    pairs = (
        db.query(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .order_by(User.id)
        .all()
    )
    return [to_out(u, p) for u, p in pairs]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    pair = (
        db.query(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .filter(User.id == user_id)
        .one_or_none()
    )
    if pair is None:
        raise HTTPException(status_code=404, detail="user not found")
    user, profile = pair
    return to_out(user, profile)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    user = User(name=payload.name, email=payload.email)
    profile = UserProfile(
        user_id=0,
        address=payload.address,
        date_of_birth=payload.date_of_birth,
    )
    db.add(user)
    db.flush()
    profile.user_id = user.id
    db.add(profile)
    db.commit()
    db.refresh(user)
    db.refresh(profile)
    return to_out(user, profile)