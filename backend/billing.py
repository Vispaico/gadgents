from sqlmodel import Session

from backend.db import User, Usage, get_user


class InsufficientCredits(Exception):
    pass


def charge(session: Session, user: User, agent_id: str, credits: int, tokens_in: int, tokens_out: int) -> None:
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
