from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.auth import get_current_user
from backend.billing import InsufficientCredits
from backend.config import get_settings
from backend.db import (
    User,
    get_session,
    EditorialRun,
    EditorialAsset,
    BrandProfile,
    PromptTemplate,
    get_or_create_dev_user,
)
from backend.llm import LLMClient
from backend.editorial import run_editorial_pipeline, EDITORIAL_PLATFORMS

router = APIRouter(prefix="/api/editorial", tags=["editorial"])

_settings = get_settings()
_llm = LLMClient()


class EditorialOut(BaseModel):
    run_id: int
    brand: dict
    ideas_count: int
    selected_ideas: int
    assets: list
    multiplier_ip: list
    credits_used: int
    remaining_credits: int


@router.post("/run", response_model=EditorialOut)
def run_editorial(
    essay: str = Body(..., embed=True),
    brand_id: int | None = Body(None, embed=True),
    platforms: list[str] | None = Body(None, embed=True),
    mode: str | None = Body(None, embed=True),
    max_ideas: int = Body(8, embed=True),
    run_multiplier: bool = Body(False, embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    if not essay or not essay.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Essay is required")
    platforms = [p for p in (platforms or []) if p in EDITORIAL_PLATFORMS]
    if brand_id is None:
        default_brand = session.exec(
            select(BrandProfile).where(BrandProfile.is_default == True)  # noqa: E712
        ).first()
        brand_id = default_brand.id if default_brand else None
    try:
        result = run_editorial_pipeline(
            session,
            user,
            essay,
            brand_id,
            platforms,
            _llm,
            mode=mode,
            max_ideas=max_ideas,
            run_multiplier=run_multiplier,
        )
    except InsufficientCredits as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    return EditorialOut(**result)


@router.get("/runs")
def list_runs(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    rows = session.exec(
        select(EditorialRun).where(EditorialRun.user_id == user.id)
        .order_by(EditorialRun.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "brand_id": r.brand_id,
            "status": r.status,
            "created_at": str(r.created_at),
            "essay_preview": (r.essay_text or "")[:120],
        }
        for r in rows
    ]


@router.get("/runs/{run_id}/assets")
def list_assets(
    run_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    run = session.get(EditorialRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    assets = session.exec(
        select(EditorialAsset).where(EditorialAsset.run_id == run_id)
    ).all()
    return [
        {
            "id": a.id,
            "idea_ref": a.idea_ref,
            "platform": a.platform,
            "kind": a.kind,
            "versions": _json_or_list(a.content),
            "quality_score": a.quality_score,
        }
        for a in assets
    ]


@router.patch("/assets/{asset_id}")
def update_asset(
    asset_id: int,
    versions: list[str] = Body(..., embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    asset = session.get(EditorialAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # Ensure the asset belongs to the user (via its run).
    run = session.get(EditorialRun, asset.run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset.content = __import__("json").dumps(versions[:4], ensure_ascii=False)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return {"id": asset.id, "versions": _json_or_list(asset.content)}


@router.get("/brands")
def list_brands(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    rows = session.exec(select(BrandProfile)).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "voice_prompt": b.voice_prompt,
            "link_url": b.link_url,
            "forbidden_phrases": b.forbidden_phrases,
            "is_default": b.is_default,
        }
        for b in rows
    ]


@router.put("/brands/{brand_id}", status_code=status.HTTP_200_OK)
def update_brand(
    brand_id: int,
    name: str | None = Body(None, embed=True),
    voice_prompt: str | None = Body(None, embed=True),
    link_url: str | None = Body(None, embed=True),
    forbidden_phrases: str | None = Body(None, embed=True),
    is_default: bool | None = Body(None, embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    brand = session.get(BrandProfile, brand_id)
    if brand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found")
    for field, val in {
        "name": name,
        "voice_prompt": voice_prompt,
        "link_url": link_url,
        "forbidden_phrases": forbidden_phrases,
        "is_default": is_default,
    }.items():
        if val is not None:
            setattr(brand, field, val)
    if is_default:
        # Only one default at a time.
        others = session.exec(
            select(BrandProfile).where(BrandProfile.id != brand_id)
        ).all()
        for o in others:
            o.is_default = False
            session.add(o)
    session.add(brand)
    session.commit()
    session.refresh(brand)
    return {
        "id": brand.id,
        "name": brand.name,
        "voice_prompt": brand.voice_prompt,
        "link_url": brand.link_url,
        "forbidden_phrases": brand.forbidden_phrases,
        "is_default": brand.is_default,
    }


@router.get("/templates")
def list_templates(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    rows = session.exec(select(PromptTemplate)).all()
    return [
        {"stage": t.stage, "version": t.version, "system_prompt": t.system_prompt}
        for t in rows
    ]


@router.put("/templates/{stage}", status_code=status.HTTP_200_OK)
def update_template(
    stage: str,
    system_prompt: str = Body(..., embed=True),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    tpl = session.exec(select(PromptTemplate).where(PromptTemplate.stage == stage)).first()
    if tpl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown stage")
    tpl.system_prompt = system_prompt
    tpl.version += 1
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return {"stage": tpl.stage, "version": tpl.version, "system_prompt": tpl.system_prompt}


def _json_or_list(s: str) -> list:
    import json

    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return [s] if s else []
