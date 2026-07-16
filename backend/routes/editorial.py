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
from backend.editorial import (
    run_editorial_pipeline,
    EDITORIAL_PLATFORMS,
    cancel_run,
    RUN_TIMEOUT_SECONDS,
)

router = APIRouter(prefix="/api/editorial", tags=["editorial"])

_settings = get_settings()
_llm = LLMClient()

# Run the (potentially long, multi-call) editorial pipeline off the request thread so
# the HTTP response returns immediately with a run_id. The frontend polls status instead
# of blocking for minutes (which previously looked like a hang while tokens kept burning).
from concurrent.futures import ThreadPoolExecutor

_editorial_executor = ThreadPoolExecutor(max_workers=2)


class EditorialOut(BaseModel):
    run_id: int
    status: str
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

    # Persist a run row immediately so the frontend can poll for status. The heavy
    # pipeline runs on a worker thread; the HTTP call returns a run_id right away.
    effective_user = user if user is not None else get_or_create_dev_user(session)
    run = EditorialRun(user_id=effective_user.id, brand_id=brand_id or 0, essay_text=essay[:8000], status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    run_id = run.id
    # Pass only the user id to the worker. Using the ORM User object loaded in THIS
    # (request) session inside the worker's separate session causes SQLAlchemy to try
    # a lazy refresh across sessions and crash ("tuple index out of range" in row
    # processing). The worker re-loads the user by id in its own session instead.
    effective_user_id = effective_user.id

    def _worker():
        # Own session + retry the DB operations outside the request session.
        from sqlmodel import Session as _S
        from backend.db import get_engine, User as _User
        from backend.editorial import EditorialCanceled

        with _S(get_engine()) as ws:
            ws_user = ws.get(_User, effective_user_id) or get_or_create_dev_user(ws)
            try:
                run_editorial_pipeline(
                    ws,
                    ws_user,
                    essay,
                    brand_id,
                    platforms,
                    _llm,
                    mode=mode,
                    max_ideas=max_ideas,
                    run_multiplier=run_multiplier,
                )
            except EditorialCanceled:
                # The pipeline already marked the run "canceled" and saved partial work.
                pass
            except InsufficientCredits as exc:
                r = ws.get(EditorialRun, run_id)
                if r:
                    r.status = "failed"
                    r.error = f"Insufficient credits: {exc}"
                    ws.add(r)
                    ws.commit()
            except Exception as exc:  # noqa: BLE001
                import traceback as _tb

                r = ws.get(EditorialRun, run_id)
                if r:
                    r.status = "failed"
                    # Store the FULL traceback (file:line + message) so a hidden
                    # IndexError/etc. is never reduced to a bare message.
                    r.error = (str(exc) + "\n" + _tb.format_exc())[:4000]
                    ws.add(r)
                    ws.commit()

    _editorial_executor.submit(_worker)

    return {
        "run_id": run_id,
        "status": "running",
        "brand": {"id": brand_id},
        "ideas_count": 0,
        "selected_ideas": 0,
        "assets": [],
        "multiplier_ip": [],
        "credits_used": 0,
        "remaining_credits": effective_user.credits if effective_user else 0,
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    # Reap OTHER stuck runs (worker died / server restarted) so they don't pile up as
    # perpetual "running". Never reap the run the caller is actively polling, and use a
    # correct UTC comparison: started_at is stored naive but represents UTC, so treat it
    # as UTC (not local time) to avoid timezone-offset false positives that would mark a
    # brand-new run failed instantly. The grace window matches RUN_TIMEOUT_SECONDS so a
    # slow-but-healthy run (the pipeline can take 5-15 min) is never reaped mid-flight.
    from datetime import datetime, timezone as _tz

    now = datetime.now(_tz.utc)
    stale = session.exec(
        select(EditorialRun).where(
            EditorialRun.user_id == user.id,
            EditorialRun.status == "running",
            EditorialRun.id != run_id,
        )
    ).all()
    for r in stale:
        started = r.started_at.replace(tzinfo=_tz.utc) if r.started_at else None
        age = (now - started).total_seconds() if started else 0
        if age > RUN_TIMEOUT_SECONDS and not r.canceled:
            r.status = "failed"
            r.error = "Run was interrupted (server restarted or worker died). Partial assets, if any, are kept."
            session.add(r)
    session.commit()
    run = session.get(EditorialRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    brand = session.get(BrandProfile, run.brand_id)
    assets = session.exec(
        select(EditorialAsset).where(EditorialAsset.run_id == run_id)
    ).all()
    return {
        "run_id": run.id,
        "status": run.status,
        "error": run.error,
        "brand": {
            "id": run.brand_id,
            "name": brand.name if brand else "",
            "link_url": brand.link_url if brand else "",
        },
        "ideas_count": run.ideas_count,
        "selected_ideas": run.ideas_count,  # ideabank count == mined count
        "assets_count": run.assets_count,
        "credits_used": run.credits_used,
        "remaining_credits": user.credits if user else 0,
        "assets": [
            {
                "id": a.id,
                "idea_ref": a.idea_ref,
                "platform": a.platform,
                "kind": a.kind,
                "versions": _json_or_list(a.content),
                "quality_score": a.quality_score,
            }
            for a in assets
        ],
        "multiplier_ip": [],  # populated in a future run if needed; kept for shape parity
    }


@router.post("/runs/{run_id}/cancel")
def cancel_editorial_run(
    run_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    """Request cancellation of a running editorial run. The worker checks the cancel
    flag between stages, so it stops (keeping partial assets) without the user having
    to kill the dev server — which would otherwise leave in-flight OpenRouter calls
    billing in the background."""
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    run = session.get(EditorialRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status not in ("running",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run is already {run.status}; nothing to cancel.",
        )
    # Mark canceled in the DB (so a fresh process / reload sees it) AND in the
    # in-memory flag the worker polls. If this process isn't the one running the
    # run, the startup reaper + the DB flag handle it on next launch.
    run.canceled = True
    run.status = "canceled"
    session.add(run)
    session.commit()
    cancel_run(run_id)
    return {"run_id": run_id, "status": "canceled"}


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
