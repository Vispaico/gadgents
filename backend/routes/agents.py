from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from backend.agents import get_agent, run_agent
from backend.auth import get_current_user
from backend.billing import InsufficientCredits, charge
from backend.db import User, get_session
from backend.llm import LLMClient

router = APIRouter(prefix="/api/agents", tags=["agents"])

_llm = LLMClient()


class ChatIn(BaseModel):
    message: str


class ChatOut(BaseModel):
    agent_id: str
    text: str
    credits_used: int
    remaining_credits: int


@router.get("")
def list_agents():
    from backend.agents import REGISTRY

    return [
        {"id": a.id, "name": a.name, "description": a.description}
        for a in REGISTRY.values()
    ]


@router.post("/{agent_id}/chat", response_model=ChatOut)
def chat(
    agent_id: str,
    payload: ChatIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    agent = get_agent(agent_id)
    if agent is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    text, t_in, t_out, credits = run_agent(agent, payload.message, _llm)
    try:
        charge(session, user, agent_id, credits, t_in, t_out)
    except InsufficientCredits as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))

    return ChatOut(
        agent_id=agent_id,
        text=text,
        credits_used=credits,
        remaining_credits=user.credits,
    )


def close_llm() -> None:
    _llm.close()
