from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session, select


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    credits: int = Field(default=0)  # remaining spendable credits
    plan: str = Field(default="free")  # free | hourly | monthly
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = Field(default=True)


class Usage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    agent_id: str
    credits_used: int
    tokens_in: int = 0
    tokens_out: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Subscription(SQLModel, table=True):
    """Long-term subscription record (populated via Stripe webhook in live mode)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    plan: str  # hourly | monthly
    provider: str = "mock"  # mock | stripe
    status: str = "active"  # active | canceled
    external_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


engine = None


def get_engine() -> "create_engine":
    global engine
    if engine is None:
        from backend.config import get_settings

        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, connect_args=connect_args)
    return engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.exec(select(User).where(User.email == email)).first()


def get_user(session: Session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)
