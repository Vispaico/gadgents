from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from backend.auth import get_current_user
from backend.billing import InsufficientCredits
from backend.config import get_settings
from backend.db import User, get_session
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


@router.post("/content", response_model=ContentOut)
def content(
    material: str = Body(..., embed=True),
    platforms: list[str] = Body(..., embed=True),
    output_mode: str = Body("content"),
    mode: str | None = None,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    try:
        result = run_content_pipeline(
            session, user, material, platforms, _llm,
            mode=mode, output_mode=output_mode,
        )
    except InsufficientCredits as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    return ContentOut(**result)
