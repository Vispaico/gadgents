"""API surface for the fusion router (model catalog + transparent selection + fusion)."""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import User, get_session
from backend.llm import LLMClient
from backend.router import (
    list_models,
    get_model,
    recommend,
    route,
    _FUSION_PRESETS,
)

router = APIRouter(prefix="/api/router", tags=["router"])

_settings = get_settings()
_llm = LLMClient()


class RouteOut(BaseModel):
    text: str
    model_id: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int


@router.get("/models")
def models():
    """Our curated model catalog (the fusion pool)."""
    return [
        {
            "id": m.id,
            "provider": m.provider,
            "model": m.model,
            "tier": m.tier,
            "modes": m.modes,
            "context_tokens": m.context_tokens,
            "description": m.description,
        }
        for m in list_models()
    ]


@router.get("/recommend")
def recommend_model(goal: str = "mixed"):
    m = recommend(goal)
    return {"id": m.id, "provider": m.provider, "model": m.model, "tier": m.tier}


@router.get("/fusion-presets")
def fusion_presets():
    """Default panel/judge per mode (high / mixed / economic)."""
    return _FUSION_PRESETS


@router.post("/chat", response_model=RouteOut)
def router_chat(
    message: str = Body(..., embed=True),
    goal: str = Body("mixed"),            # high | mixed | economic
    model_id: str | None = Body(None),    # pin an exact catalog model
    fusion: bool = Body(False),           # run panel + judge
    panel: list[str] | None = Body(None), # custom panel model ids (fusion only)
    judge: str | None = Body(None),       # custom judge model id (fusion only)
    system_prompt: str | None = Body(None),
    temperature: float = Body(0.7),
    max_tokens: int = Body(2048),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    entry = get_model(model_id) if model_id else recommend(goal)
    if model_id and entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model_id")
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": message})
    text, used_id = route(
        _llm,
        messages,
        goal=goal,
        model_id=model_id,
        fusion=fusion,
        panel=panel,
        judge=judge,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    resolved = get_model(used_id) if not used_id.startswith("fusion:") else None
    provider = resolved.provider if resolved else "fusion"
    model = resolved.model if resolved else used_id
    return RouteOut(
        text=text,
        model_id=used_id,
        provider=provider,
        model=model,
        tokens_in=0,
        tokens_out=0,
    )


def close_router_llm() -> None:
    _llm.close()
