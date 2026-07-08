from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlmodel import Session

from backend.auth import create_access_token, hash_password, verify_password
from backend.config import get_settings
from backend.db import User, get_session, get_user_by_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

_settings = get_settings()


class RegisterIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    credits: int
    plan: str


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, session: Session = Depends(get_session)):
    if get_user_by_email(session, payload.email):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        credits=_settings.free_credits_on_signup,
        plan="free",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenOut(
        access_token=create_access_token(user.id),
        credits=user.credits,
        plan=user.plan,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenOut(
        access_token=create_access_token(user.id),
        credits=user.credits,
        plan=user.plan,
    )
