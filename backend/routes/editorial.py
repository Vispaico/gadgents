from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

import time

from backend.auth import get_current_user
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
from backend.editorial import (
    EDITORIAL_PLATFORMS,
    cancel_run,
    RUN_TIMEOUT_SECONDS,
)

router = APIRouter(prefix="/api/editorial", tags=["editorial"])

_settings = get_settings()

# Run the (potentially long, multi-call) editorial pipeline in a SEPARATE PROCESS (not a
# thread). OpenRouter intermittently stalls a connection (accepts the request but never
# streams a response and never closes). On CPython/macOS a socket stuck in ssl.recv is
# NOT interruptible by httpx/socket timeouts or a worker-thread future, so it blocks
# forever and keeps billing. A subprocess is the only reliable kill: SIGKILL cannot be
# ignored by a blocked recv, so Cancel can `process.kill()` a wedged run instantly. The
# HTTP response returns immediately with a run_id; the frontend polls status instead of
# blocking for minutes (which previously looked like a hang while tokens kept burning).
import subprocess
import sys
import threading

# Track live run subprocesses so Cancel can kill a wedged one unblockably.
_editorial_processes: dict[int, subprocess.Popen] = {}

# Hard ceiling (seconds) a SINGLE editorial subprocess may live, even if it never hits a
# stall we can detect. OpenRouter stalls are invisible to in-process timeouts, so if the
# per-stage SIGALRM hasn't fired (it's best-effort), this watchdog SIGKILLs the process
# and resolves the row. Kept generous but finite so a wedged run can NEVER hang the UI
# forever — the user sees a failed run, not an eternal "Engine running…".
_EDITORIAL_PROCESS_HARD_CAP_S = 3 * 60  # 3 minutes (the per-call subprocess timeout
                                  # is the real stall-killer; this is the backstop)


def _editorial_watchdog() -> None:
    """Background thread in the uvicorn process: the reliable safety net for stalled
    editorial runs. For every tracked run it (a) reaps the row if the child died but left
    it 'running', and (b) SIGKILLs a child that outlived the hard cap. SIGKILL cannot be
    ignored by a blocked recv, so this always works even when the subprocess's own
    SIGALRM timeout doesn't fire."""
    from sqlmodel import Session as _S
    from backend.db import get_engine, EditorialRun as _ER

    while True:
        try:
            time.sleep(15)
            dead: list[int] = []
            for rid, proc in list(_editorial_processes.items()):
                try:
                    if proc.poll() is not None:
                        # Child ended (crashed, killed, or finished). If the row is still
                        # 'running' it was left orphaned — resolve it as failed so the UI
                        # never shows a permanent spinner. (A clean finish writes 'done'
                        # before exit; a Cancel already wrote 'canceled'.)
                        with _S(get_engine()) as ws:
                            r = ws.get(_ER, rid)
                            if r is not None and r.status == "running":
                                r.status = "failed"
                                r.error = (
                                    "Editorial worker process ended without updating the "
                                    "run (crash or kill). Partial assets, if any, are kept."
                                )
                                ws.add(r)
                                ws.commit()
                        dead.append(rid)
                    elif getattr(proc, "_start_time", 0) and (
                        time.time() - proc._start_time > _EDITORIAL_PROCESS_HARD_CAP_S
                    ):
                        # Over the hard cap and still alive: almost certainly stalled. Kill.
                        try:
                            proc.kill()
                            proc.wait(timeout=3)
                        except Exception:
                            pass
                        with _S(get_engine()) as ws:
                            r = ws.get(_ER, rid)
                            if r is not None and r.status == "running":
                                r.status = "failed"
                                r.error = (
                                    "Editorial run exceeded the hard process cap "
                                    f"({_EDITORIAL_PROCESS_HARD_CAP_S // 60} min) and was "
                                    "terminated to stop token burn."
                                )
                                ws.add(r)
                                ws.commit()
                        dead.append(rid)
                except Exception:
                    # Never let the watchdog itself die; keep protecting other runs.
                    continue
            for rid in dead:
                _editorial_processes.pop(rid, None)
        except Exception:
            continue


# Launch the watchdog once (daemon thread; dies with the process). Guarded so re-imports
# of this module (e.g. under multiprocessing spawn) don't spawn extra watchdogs.
# NOTE: do NOT gate on `current_thread() is main_thread()` — uvicorn imports the app from
# a worker thread, so that check is False and the watchdog never starts, leaving stalled runs
# to hang forever (the "running" row that nothing reaps). Start unconditionally at import.
_WATCHDOG_STARTED = False
if not _WATCHDOG_STARTED:
    _WATCHDOG_STARTED = True
    threading.Thread(target=_editorial_watchdog, name="editorial-watchdog", daemon=True).start()


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

    # Run in a SEPARATE PROCESS (see subprocess.Popen launch below) so a stalled OpenRouter
    # recv can be SIGKILLed unblockably, and the per-stage SIGALRM in editorial.py can fire
    # from the worker's main thread.

    # Launch as a CLEAN subprocess via subprocess.Popen (NOT multiprocessing). multiprocessing
    # spawn re-imports __main__ and pickles the target, which intermittently killed the worker
    # INSTANTLY when launched from uvicorn's threadpool — the run row was left 'running' forever
    # with no process and no API call (the "4 min, nothing happens" bug). A bare subprocess is a
    # fresh interpreter, takes args as strings (no pickle), and Popen.kill() SIGKILLs it.
    import json

    cmd = [
        sys.executable, "-m", "backend.editorial_worker",
        str(run_id),
        essay,
        str(brand_id if brand_id is not None else ""),
        json.dumps(platforms or []),
        mode or "",
        str(max_ideas),
        str(bool(run_multiplier)),
        str(effective_user_id),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc._start_time = time.time()
    _editorial_processes[run_id] = proc

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
    # Reap stuck "running" rows: OTHER runs (older than the 20-min guardrail), and the
    # CURRENTLY-polled run too IF it has blown well past the wall-clock deadline. A live,
    # healthy run is auto-canceled by its own guardrail before then, so anything still
    # "running" past RUN_TIMEOUT_SECONDS has a dead worker and must be resolved — otherwise
    # it sits at 0 forever and can't be canceled (the bug we hit). The run being actively
    # polled is intentionally included here for that reason.
    stale = session.exec(
        select(EditorialRun).where(
            EditorialRun.user_id == user.id,
            EditorialRun.status == "running",
        )
    ).all()
    for r in stale:
        started = r.started_at.replace(tzinfo=_tz.utc) if r.started_at else None
        age = (now - started).total_seconds() if started else 0
        if age > RUN_TIMEOUT_SECONDS and not r.canceled:
            r.status = "failed"
            r.error = (
                "Run exceeded the time guard and was marked failed (server restarted or "
                "worker died). Partial assets, if any, are kept."
            )
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
    # If we have the live subprocess handle, SIGKILL it. This unblockably terminates a
    # run wedged in a stalled OpenRouter recv (the only reliable kill for that case) --
    # killing the server was previously the only way, which still leaked in-flight calls.
    proc = _editorial_processes.pop(run_id, None)
    if proc is not None and proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
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
