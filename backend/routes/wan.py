"""Wan2.2 image-to-video prompt endpoint (agent #4).

Takes a source image reference + concept/script/mood (+ optional format preset), runs the
multi-model `wan-video` agent (Fusion panel + judge), parses the structured storyboard, and
persists a canonical brief + per-shot Wan prompts for history / regeneration.
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
    WanVideoBrief,
    WanVideoShot,
)
from backend.llm import LLMClient

router = APIRouter(prefix="/api/wan", tags=["wan"])

_settings = get_settings()
_llm = LLMClient()


@router.post("/run")
def run(
    source_image: str = Body("", embed=True),
    concept: str = Body(..., embed=True),
    format_kind: str = Body("", embed=True),
    title: str = Body(""),
    mode: str | None = None,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    agent = get_agent("wan-video")
    if agent is None or not agent.production_ready:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    user_msg = (
        f"SOURCE IMAGE (first frame / seed): {source_image or '(none provided)'}\n"
        f"FORMAT PRESET (optional structure): {format_kind or 'free / unspecified'}\n"
        f"CONCEPT / SCRIPT / MOOD:\n\"\"\"\n{concept}\n\"\"\"\n\n"
        "Produce the storyboard of Wan2.2 image-to-video shots following your contract."
    )

    text, _ti, _to, credits = run_agent(agent, user_msg, _llm, memory=None, override_mode=mode)

    try:
        data = json.loads(text)
        parsed = True
    except json.JSONDecodeError:
        data = {"raw": text}
        parsed = False

    brief_id = None
    if user is not None and parsed:
        brief = WanVideoBrief(
            user_id=user.id,
            title=title or data.get("title", "") or "Wan storyboard",
            source_image=source_image,
            concept=concept[:4000],
            format_kind=format_kind,
            brief_json=json.dumps(data, ensure_ascii=False),
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)
        brief_id = brief.id
        for shot in data.get("shots", []):
            session.add(WanVideoShot(
                brief_id=brief_id,
                user_id=user.id,
                shot_number=int(shot.get("shot", 0)),
                camera=shot.get("camera", ""),
                frame=shot.get("frame", ""),
                action=shot.get("action", ""),
                look=shot.get("look", ""),
                wan_prompt=shot.get("wan_prompt", ""),
                model="fusion:or-opus",
            ))
        session.commit()

    return {
        "text": text,
        "credits_used": 0 if not _settings.enable_paywall else credits,
        "parsed": parsed,
        "brief_id": brief_id,
        "title": title or (data.get("title", "") if parsed else ""),
    }


@router.get("/briefs")
def list_briefs(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    rows = session.exec(select(WanVideoBrief).where(WanVideoBrief.user_id == user.id)).all()
    return [
        {"id": r.id, "title": r.title, "format_kind": r.format_kind,
         "created_at": str(r.created_at)}
        for r in rows
    ]


def close_wan_llm() -> None:
    _llm.close()
