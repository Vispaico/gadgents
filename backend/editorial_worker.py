"""Subprocess worker for Editorial Studio runs.

WHY A SEPARATE PROCESS (not a thread):
The editorial pipeline makes dozens of sequential OpenRouter calls. OpenRouter
intermittently *stalls* a connection (accepts the request but never streams a
response body and never closes it). On CPython/macOS, a socket stuck in
`ssl.recv` for such a half-open connection is NOT interruptible by httpx's own
read timeout, by socket timeouts, by closing the client, or by a worker-thread
future timeout -- it blocks indefinitely. We proved this empirically: a run
wedged at stage 2 (strategist) for 10+ minutes burning tokens, producing 0
assets, and could only be stopped by killing the dev server (which still left
in-flight OpenRouter calls billing in the background).

A subprocess is the only mechanism that reliably kills that stall: SIGKILL
cannot be ignored by a blocked recv, so `process.kill()` always terminates the
run. We also arm a per-stage SIGALRM inside the subprocess (its main thread, so
the signal DOES interrupt the recv and turns a stall into a clean exception) as a
second safety net.

The route launches this via multiprocessing and keeps the Process handle so the
Cancel endpoint can `process.kill()` a wedged run.
"""

from __future__ import annotations

import signal
import traceback
from typing import Optional

from sqlmodel import Session

from backend.db import (
    EditorialRun,
    BrandProfile,
    User,
    get_engine,
    get_or_create_dev_user,
)
from backend.llm import LLMClient
from backend.editorial import run_editorial_pipeline, EditorialCanceled


# Stages may take a long time on a slow/loaded provider. A stall here would burn
# tokens forever; cap each at this many seconds. If a stage exceeds it, SIGALRM
# raises inside the subprocess main thread (unlike a worker thread) and the run
# fails fast instead of hanging. Tuned well above a healthy call (>120s is abnormal
# on OpenRouter).
_STAGE_HARD_TIMEOUT_S = 150


def _stage_alarm_handler(signum, frame):
    raise TimeoutError(
        f"Editorial stage exceeded the {_STAGE_HARD_TIMEOUT_S}s hard timeout "
        "(provider stalled). Aborting run to stop token burn."
    )


def run_worker(
    run_id: int,
    essay: str,
    brand_id: Optional[int],
    platforms: Optional[list[str]],
    mode: Optional[str],
    max_ideas: int,
    run_multiplier: bool,
    user_id: int,
) -> None:
    """Entry point executed in the subprocess. Runs ONE editorial pipeline and writes
    its outcome back to the DB. Any failure is recorded (never left as 'running')."""
    # The subprocess main thread can receive SIGALRM, so the per-stage timeout works.
    signal.signal(signal.SIGALRM, _stage_alarm_handler)
    llm = LLMClient()
    try:
        with Session(get_engine()) as ws:
            user = ws.get(User, user_id)
            if user is None:
                user = get_or_create_dev_user(ws)
            brand = ws.get(BrandProfile, brand_id) if brand_id else None
            b_id = brand.id if brand else (brand_id or 0)
            try:
                # Arm the hard timeout just before the (long) pipeline call. The pipeline
                # checks its own cancel/guardrails between stages; SIGALRM backs that up
                # against a single stalled HTTP call that those checks never reach.
                signal.alarm(_STAGE_HARD_TIMEOUT_S)
                run_editorial_pipeline(
                    ws,
                    user,
                    essay,
                    b_id,
                    platforms or [],
                    llm,
                    mode=mode,
                    max_ideas=max_ideas,
                    run_multiplier=run_multiplier,
                )
            except EditorialCanceled:
                pass  # pipeline already marked the run canceled + saved partial work
            except TimeoutError as exc:
                _mark_failed(ws, run_id, f"Aborted: {exc}")
            except Exception as exc:  # noqa: BLE001
                _mark_failed(ws, run_id, str(exc) + "\n" + traceback.format_exc())
            finally:
                signal.alarm(0)
    except Exception as exc:  # noqa: BLE001 - any setup failure must resolve the row
        try:
            with Session(get_engine()) as ws:
                _mark_failed(ws, run_id, "Worker setup error: " + str(exc)[:500])
        except Exception:
            pass
    finally:
        try:
            llm.close()
        except Exception:
            pass


def _mark_failed(session: Session, run_id: int, error: str) -> None:
    r = session.get(EditorialRun, run_id)
    if r and r.status == "running":
        r.status = "failed"
        r.error = error[:4000]
        session.add(r)
        session.commit()
