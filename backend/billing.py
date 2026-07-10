from sqlmodel import Session

from backend.config import get_settings
from backend.db import User, Usage, get_user

_settings = get_settings()


class InsufficientCredits(Exception):
    pass


def charge(session: Session, user: User, agent_id: str, credits: int, tokens_in: int, tokens_out: int) -> None:
    # Dev / preview mode: when the paywall is off, never deduct or block.
    if not _settings.enable_paywall:
        if session and user is not None:
            session.add(
                Usage(
                    user_id=user.id,
                    agent_id=agent_id,
                    credits_used=0,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            )
            session.commit()
        return
    if user is None:
        return
    if user.credits < credits:
        raise InsufficientCredits(
            f"Not enough credits. Need {credits}, have {user.credits}. Buy credits to continue."
        )
    user.credits -= credits
    session.add(
        Usage(
            user_id=user.id,
            agent_id=agent_id,
            credits_used=credits,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    session.add(user)
    session.commit()


def add_credits(session: Session, user: User, credits: int) -> User:
    user.credits += credits
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
