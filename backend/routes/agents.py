from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from backend.agents import list_production_agents, get_agent, run_agent
from backend.auth import get_current_user
from backend.billing import InsufficientCredits, charge
from backend.config import get_settings
from backend.db import User, get_session
from backend.llm import LLMClient

router = APIRouter(prefix="/api/agents", tags=["agents"])

_settings = get_settings()
_llm = LLMClient()


class ChatOut(BaseModel):
    agent_id: str
    text: str
    credits_used: int
    remaining_credits: int


@router.get("")
def list_agents():
    # Only agents flagged production_ready are exposed; no router edits needed for new agents.
    return [
        {"id": a.id, "name": a.name, "description": a.description, "model": a.model}
        for a in list_production_agents()
    ]


@router.post("/{agent_id}/chat", response_model=ChatOut)
def chat(
    agent_id: str,
    message: str = Body(..., embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None

    agent = get_agent(agent_id)
    if agent is None or not agent.production_ready:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    text, t_in, t_out, credits = run_agent(agent, message, _llm)

    remaining_credits = 0
    if _settings.enable_paywall and user is not None:
        try:
            charge(session, user, agent_id, credits, t_in, t_out)
            remaining_credits = user.credits
        except InsufficientCredits as exc:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    elif user is not None:
        # Dev bypass: track credits in the response without deducting.
        remaining_credits = user.credits

    return ChatOut(
        agent_id=agent_id,
        text=text,
        credits_used=0 if not _settings.enable_paywall else credits,
        remaining_credits=remaining_credits,
    )


def close_llm() -> None:
    _llm.close()
