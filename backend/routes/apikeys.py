"""API key management for Hermes agents / MCP clients.

API keys are long-lived (no expiry) machine-to-machine credentials. Each key
maps to a Gadgents user, so credits/paywall/free_access are handled transparently.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import ApiKey, User, get_session, create_api_key

router = APIRouter(prefix="/api/apikeys", tags=["apikeys"])

_settings = get_settings()


@router.post("")
def create(
    label: str = Body("", embed=True),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    raw_key, row = create_api_key(user.id, label.strip() or "Hermes agent")
    session.add(row)
    session.commit()
    return {
        "id": row.id,
        "label": row.label,
        "api_key": raw_key,
        "created_at": str(row.created_at),
        "note": "Store this key now — it will never be shown again.",
    }


@router.get("")
def list_keys(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        select(ApiKey).where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "label": r.label,
            "key_hash_truncated": r.key_hash[:8] + "…",
            "created_at": str(r.created_at),
        }
        for r in rows
    ]


@router.delete("/{key_id}")
def delete(
    key_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    key = session.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    session.delete(key)
    session.commit()
    return {"deleted": key_id}
