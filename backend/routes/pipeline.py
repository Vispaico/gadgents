from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.auth import get_current_user
from backend.billing import InsufficientCredits
from backend.config import get_settings
from backend.db import User, get_session, ContentBrief, ContentOutput, get_or_create_dev_user
from backend.llm import LLMClient
from backend.pipeline import run_content_pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_settings = get_settings()
_llm = LLMClient()


class ContentOut(BaseModel):
    prompts: str
    content: str
    credits_used: int
    remaining_credits: int
    brief_id: int | None = None


@router.post("/content", response_model=ContentOut)
def content(
    material: str = Body(..., embed=True),
    platforms: list[str] = Body(..., embed=True),
    output_mode: str = Body("content"),
    urls: list[str] = Body([]),
    instructions: str = Body(""),
    mode: str | None = None,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    try:
        result = run_content_pipeline(
            session, user, material, platforms, _llm,
            mode=mode, output_mode=output_mode, urls=urls, instructions=instructions,
        )
    except InsufficientCredits as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    return ContentOut(**result)


@router.get("/briefs")
def list_briefs(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    # In dev-bypass mode there is no real user; read the synthetic dev user's history.
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    rows = session.exec(
        select(ContentBrief).where(ContentBrief.user_id == user.id)
        .order_by(ContentBrief.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "title": r.source_title or "(untitled)",
            "channels": r.channels,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


@router.get("/briefs/{brief_id}")
def get_brief(
    brief_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    brief = session.get(ContentBrief, brief_id)
    if brief is None or brief.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brief not found")
    outputs = session.exec(
        select(ContentOutput).where(ContentOutput.brief_id == brief_id)
    ).all()
    return {
        "id": brief.id,
        "title": brief.source_title or "(untitled)",
        "channels": brief.channels,
        "created_at": str(brief.created_at),
        "brief_json": brief.brief_json,
        "outputs": [
            {
                "channel": o.channel,
                "content_json": o.content_json,
                "model": o.model,
            }
            for o in outputs
        ],
    }
