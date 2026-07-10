"""Personal Secretary & Planner subsystem endpoints.

The `personal-planner` agent is the brain; these endpoints persist its structured
output into the proactive-subsystem tables (tasks, time_blocks, reminders, learned
preferences) so a future scheduled loop + delivery channel can drive it. This module
is channel-agnostic (no Telegram assumed).
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.agents import get_agent, run_agent
from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import (
    User,
    get_session,
    InboxItem,
    Task,
    TimeBlock,
    Reminder,
    PlannerMemory,
    set_memory,
    get_memories,
)
from backend.llm import LLMClient

router = APIRouter(prefix="/api/planner", tags=["planner"])

_settings = get_settings()
_llm = LLMClient()


def _memory_blob(session: Session, user: User) -> str:
    rows = get_memories(session, user.id)
    if not rows:
        return ""
    return "\n".join(f"- {r.key}: {r.value} (confidence {r.confidence})" for r in rows)


@router.post("/plan")
def plan(
    message: str = Body(..., embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    """Run the planner on a brain-dump; persist tasks/blocks/reminders + learned prefs."""
    if not _settings.require_login:
        user = None
    agent = get_agent("personal-planner")
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    memory = _memory_blob(session, user) if user else ""
    text, t_in, t_out, credits = run_agent(agent, message, _llm, memory=memory if memory else None)

    # Persist when we have a user (skipped in dev bypass with no user).
    if user is not None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if data:
            for t in data.get("tasks", []):
                session.add(Task(user_id=user.id, **_task_fields(t)))
            for b in data.get("time_blocks", []):
                session.add(TimeBlock(user_id=user.id, **_block_fields(b)))
            for r in data.get("reminders", []):
                session.add(Reminder(user_id=user.id, **_reminder_fields(r)))
            for learned in data.get("learned", []):
                set_memory(
                    session, user.id, learned.get("key", ""),
                    learned.get("value", ""), int(learned.get("confidence", 2)),
                )
            session.commit()

    return {
        "text": text,
        "credits_used": 0 if not _settings.enable_paywall else credits,
        "parsed": data if user is not None else None,
    }


def _task_fields(t: dict) -> dict:
    due = t.get("due")
    return {
        "title": t.get("title", ""),
        "next_action": t.get("next_action", ""),
        "duration_min": int(t.get("duration_min", 30)),
        "urgency": int(t.get("urgency", 3)),
        "confidence": int(t.get("confidence", 3)),
        "due": _parse_dt(due),
    }


def _block_fields(b: dict) -> dict:
    return {
        "title": b.get("title", ""),
        "start": _parse_dt(b["start"]),
        "end": _parse_dt(b["end"]),
        "kind": b.get("kind", "task"),
        "focus": bool(b.get("focus", False)),
    }


def _reminder_fields(r: dict) -> dict:
    return {
        "trigger_at": _parse_dt(r["trigger_at"]),
        "stage": int(r.get("stage", 1)),
        "channel": r.get("channel", "inbox"),
        "message": r.get("message", ""),
    }


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


@router.post("/inbox")
def capture(
    raw_text: str = Body(..., embed=True),
    source: str = Body("chat"),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    if user is None:
        return {"status": "dev-bypass", "note": "no user; start server with login to persist"}
    item = InboxItem(user_id=user.id, raw_text=raw_text, source=source)
    session.add(item)
    session.commit()
    return {"id": item.id, "status": item.status}


@router.get("/tasks")
def list_tasks(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    return list(session.exec(select(Task).where(Task.user_id == user.id)).all())


@router.get("/reminders")
def list_reminders(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    return list(session.exec(select(Reminder).where(Reminder.user_id == user.id)).all())


@router.get("/memory")
def list_memory(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        return []
    return [{"key": m.key, "value": m.value, "confidence": m.confidence} for m in get_memories(session, user.id)]


def close_planner_llm() -> None:
    _llm.close()
