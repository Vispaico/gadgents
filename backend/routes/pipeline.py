from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from backend.auth import get_current_user
from backend.billing import InsufficientCredits
from backend.db import User, get_session
from backend.llm import LLMClient
from backend.pipeline import run_content_pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_llm = LLMClient()


class ContentIn(BaseModel):
    material: str
    platforms: list[str]


class ContentOut(BaseModel):
    prompts: str
    content: str
    credits_used: int
    remaining_credits: int


@router.post("/content", response_model=ContentOut)
def content(
    payload: ContentIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        result = run_content_pipeline(
            session, user, payload.material, payload.platforms, _llm
        )
    except InsufficientCredits as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    return ContentOut(**result)
