import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.auth import create_access_token, get_current_user, hash_password, verify_password
from backend.config import get_settings
from backend.db import User, get_session, get_user_by_email
from backend.email import send_verification_email, send_password_reset_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

_settings = get_settings()
_email_executor = ThreadPoolExecutor(max_workers=2)


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
    email_verified: bool = False


class MeOut(BaseModel):
    email: str
    credits: int
    plan: str
    email_verified: bool
    role: str


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str


def _send_verify(to: str, token: str):
    send_verification_email(to, token)


def _send_reset(to: str, token: str):
    send_password_reset_email(to, token)


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, session: Session = Depends(get_session)):
    if get_user_by_email(session, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    token = uuid.uuid4().hex
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        credits=_settings.free_credits_on_signup,
        plan="free",
        verification_token=token,
        email_verified=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    # Send verification email — fire-and-forget, doesn't block registration.
    _email_executor.submit(_send_verify, user.email, token)
    return TokenOut(
        access_token=create_access_token(user.id),
        credits=user.credits,
        plan=user.plan,
        email_verified=user.email_verified,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, session: Session = Depends(get_session)):
    user = get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenOut(
        access_token=create_access_token(user.id),
        credits=user.credits,
        plan=user.plan,
        email_verified=user.email_verified,
    )


@router.post("/verify/{token}")
def verify_email(token: str, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.verification_token == token)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired verification token")
    user.email_verified = True
    user.verification_token = None
    session.add(user)
    session.commit()
    return {"ok": True, "message": "Email verified. You can now use all agents."}


@router.post("/resend-verification")
def resend_verification(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if user.email_verified:
        return {"ok": True, "message": "Email already verified."}
    token = uuid.uuid4().hex
    user.verification_token = token
    session.add(user)
    session.commit()
    _email_executor.submit(_send_verify, user.email, token)
    return {"ok": True, "message": "Verification email sent."}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, session: Session = Depends(get_session)):
    # Always return 200 — don't leak whether an email is registered.
    user = get_user_by_email(session, payload.email)
    if user is not None:
        token = uuid.uuid4().hex
        user.verification_token = token
        session.add(user)
        session.commit()
        _email_executor.submit(_send_reset, user.email, token)
    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.verification_token == payload.token)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired reset token")
    user.hashed_password = hash_password(payload.password)
    user.verification_token = None
    user.email_verified = True  # implicit verification — you proved you own the inbox
    session.add(user)
    session.commit()
    return {"ok": True, "message": "Password reset. You can now log in."}


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return MeOut(
        email=user.email,
        credits=user.credits,
        plan=user.plan,
        email_verified=user.email_verified,
        role=user.role,
    )
