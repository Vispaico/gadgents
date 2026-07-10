"""Content Repurposer endpoint (agent #2).

Takes an article/essay + selected channels + tone/audience, runs the multi-model
`content-repurposer` agent (Fusion panel + judge), parses the structured result, and
persists a canonical brief + per-channel outputs for later history / regeneration.
"""

import json
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.agents import get_agent, run_agent
from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import (
    User,
    get_session,
    ContentBrief,
    ContentOutput,
)
from backend.llm import LLMClient

router = APIRouter(prefix="/api/repurposer", tags=["repurposer"])

_settings = get_settings()
_llm = LLMClient()

VALID_CHANNELS = ["linkedin", "facebook", "x", "instagram", "youtube", "shorts_tiktok"]


@router.post("/run")
def run(
    article: str = Body(..., embed=True),
    channels: list[str] = Body(VALID_CHANNELS),
    tone: str = Body("direct, pragmatic, no fluff"),
    audience: str = Body("general"),
    title: str = Body(""),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    agent = get_agent("content-repurposer")
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    selected = [c for c in channels if c in VALID_CHANNELS] or VALID_CHANNELS
    user_msg = (
        f"Source title: {title or '(none)'}\n"
        f"Audience: {audience}\n"
        f"Brand voice/tone: {tone}\n"
        f"Produce outputs for these platforms ONLY: {', '.join(selected)}.\n"
        f"If 'shorts_tiktok' is selected, also produce the script package and media_suggestions.\n\n"
        f"ARTICLE / ESSAY:\n\"\"\"\n{article}\n\"\"\""
    )

    text, _ti, _to, credits = run_agent(agent, user_msg, _llm, memory=None)

    # Parse structured result (best-effort). Fall back to raw text if not JSON.
    try:
        data = json.loads(text)
        parsed = True
    except json.JSONDecodeError:
        data = {"raw": text}
        parsed = False

    brief_id = None
    if user is not None and parsed:
        brief = ContentBrief(
            user_id=user.id,
            source_title=title,
            source_text=article[:4000],
            channels=",".join(selected),
            tone=tone,
            audience=audience,
            brief_json=json.dumps(data.get("brief", {}), ensure_ascii=False),
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        brief_id = brief.id
        # Persist channel outputs individually for easy regeneration/history.
        for ch in selected:
            block = data.get("posts", {}).get(ch)
            if block:
                session.add(ContentOutput(
                    brief_id=brief_id, user_id=user.id, channel=ch,
                    variant_index=0, content_json=json.dumps(block, ensure_ascii=False),
                    model="fusion:or-opus",
                ))
        if "script" in data:
            session.add(ContentOutput(
                brief_id=brief_id, user_id=user.id, channel="script",
                content_json=json.dumps(data["script"], ensure_ascii=False),
                model="fusion:or-opus",
            ))
        if "media_suggestions" in data:
            session.add(ContentOutput(
                brief_id=brief_id, user_id=user.id, channel="media",
                content_json=json.dumps(data["media_suggestions"], ensure_ascii=False),
                model="fusion:or-opus",
            ))
        session.commit()

    return {
        "text": text,
        "credits_used": 0 if not _settings.enable_paywall else credits,
        "parsed": parsed,
        "brief_id": brief_id,
        "channels": selected,
    }


@router.get("/briefs")
def list_briefs(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    rows = session.exec(select(ContentBrief).where(ContentBrief.user_id == user.id)).all()
    return [
        {"id": r.id, "title": r.source_title, "channels": r.channels,
         "created_at": str(r.created_at)}
        for r in rows
    ]


def close_repurposer_llm() -> None:
    _llm.close()
