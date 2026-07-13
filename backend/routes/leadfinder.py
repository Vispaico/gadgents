"""Lead Finder endpoint (agent #3).

Frontend flow:
  - POST /api/leadfinder/icp-chat : conversational ICP refinement (uses the agent's
    chat model; returns the model text so the UI can drive a wizard).
  - POST /api/leadfinder/run      : runs the full discovery chain for a given ICP,
    persists the query + leads, returns the structured result.
  - GET  /api/leadfinder/leads    : list past runs + their leads for the user.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Optional

from backend.agents import get_agent, run_agent
from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import (
    Lead,
    LeadQuery,
    User,
    get_session,
)
from backend.leads.agent import run_and_persist
from backend.leads.models import ICPInput
from backend.llm import LLMClient

router = APIRouter(prefix="/api/leadfinder", tags=["leadfinder"])

_settings = get_settings()
_llm = LLMClient()


class ChatOut(BaseModel):
    agent_id: str
    text: str
    credits_used: int
    remaining_credits: int


@router.post("/icp-chat", response_model=ChatOut)
def icp_chat(
    message: str = Body(..., embed=True),
    history: list[dict] = Body(default=[]),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    agent = get_agent("lead-finder")
    if agent is None or not agent.production_ready:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    text, _ti, _to, credits = run_agent(agent, message, _llm,
                                        memory=_format_history(history))
    return ChatOut(
        agent_id="lead-finder",
        text=text,
        credits_used=0 if not _settings.enable_paywall else credits,
        remaining_credits=user.credits if user else 0,
    )


@router.post("/run")
def run(
    icp: ICPInput,
    mode: str | None = None,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    agent = get_agent("lead-finder")
    if agent is None or not agent.production_ready:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    result = run_and_persist(icp, _llm, session, user=user, mode=mode)
    return {
        "icp": result.icp.model_dump(),
        "leads": [l.model_dump() for l in result.leads],
        "gdpr_note": result.gdpr_note,
        "credits_used": 0 if not _settings.enable_paywall else agent.base_credits,
    }


@router.get("/leads")
def list_leads(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    queries = session.exec(
        select(LeadQuery).where(LeadQuery.user_id == user.id)
        .order_by(LeadQuery.created_at.desc())
    ).all()
    out = []
    for q in queries:
        leads = session.exec(select(Lead).where(Lead.query_id == q.id)).all()
        out.append({
            "query_id": q.id,
            "name": q.name,
            "offer": q.offer,
            "geography": q.geography,
            "created_at": str(q.created_at),
            "leads": [
                {
                    "domain": l.domain,
                    "fit_score": l.fit_score,
                    "emails": l.emails_json,
                    "status": l.status,
                    "suggested_angle": l.suggested_angle,
                }
                for l in leads
            ],
        })
    return out


def _format_history(history: list[dict]) -> str:
    if not history:
        return None
    lines = []
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def close_leadfinder_llm() -> None:
    _llm.close()
