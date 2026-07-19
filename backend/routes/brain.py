"""Brain endpoint: server-side save of a result into the local OpenKB knowledge base.

The frontend "Save to Brain" button posts the result here. We write it as a Markdown file
into the brain's `raw/` dir and run `openkb add` so it is compiled into the wiki (topic/entity
pages + cross-links). openkb is an OPTIONAL dependency: if it isn't installed, the file is still
written (so nothing is lost) and the route returns a clear "openkb not installed" note.

openkb authenticates via env vars. The brain model lives on OpenRouter (openrouter/...), so we
inject OPENROUTER_API_KEY from the app's .env into the subprocess environment.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, status

from backend.config import get_settings

router = APIRouter(prefix="/api/brain", tags=["brain"])

# Brain lives at <project>/brain (where `openkb init` was run).
_BRAIN_DIR = Path(__file__).resolve().parent.parent.parent / "brain"


def _slug(title: str) -> str:
    slug = title.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-_").strip("-")
    return slug[:60] or "note"


def _brain_env() -> dict:
    """Build the env for the openkb subprocess, injecting auth from app settings."""
    env = dict(os.environ)
    s = get_settings()
    # The compile step needs an LLM key. The brain model is on OpenRouter.
    if s.openrouter_api_key:
        env["OPENROUTER_API_KEY"] = s.openrouter_api_key
        if not env.get("LLM_API_KEY"):
            env["LLM_API_KEY"] = s.openrouter_api_key
    return env


def _ensure_init(env: dict) -> None:
    """Make sure the brain KB is initialized (openkb init), if not already."""
    if (_BRAIN_DIR / ".openkb").exists():
        return
    _BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    # `openkb init` is interactive; feed it empty lines to accept all defaults.
    proc = subprocess.run(
        ["openkb", "init"],
        cwd=str(_BRAIN_DIR),
        env=env,
        input="\n\n\n",
        text=True,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0 and not (_BRAIN_DIR / ".openkb").exists():
        raise RuntimeError(f"openkb init failed: {proc.stderr[:500]}")


@router.post("/save")
def brain_save(
    title: str = Body(..., embed=True),
    body: str = Body(..., embed=True),
    meta: dict = Body({}),
):
    if not title.strip() or not body.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title and body required")

    raw_dir = _BRAIN_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname = f"{stamp}-{_slug(title)}.md"

    fm = "\n".join(f"- {k}: {v}" for k, v in (meta or {}).items())
    md = f"# {title}\n\n> saved: {stamp}{('\n' + fm) if fm else ''}\n\n{body}\n"
    fpath = raw_dir / fname
    fpath.write_text(md, encoding="utf-8")

    # openkb is optional; if missing, keep the file and tell the caller.
    if not _have_openkb():
        return {
            "saved_file": str(fpath),
            "indexed": False,
            "note": "openkb not installed — file saved to brain/raw. Run `pip install openkb` to index it.",
        }

    env = _brain_env()
    try:
        _ensure_init(env)
    except Exception as exc:  # noqa: BLE001
        return {"saved_file": str(fpath), "indexed": False, "note": f"KB init skipped: {exc}"}

    try:
        proc = subprocess.run(
            ["openkb", "add", str(fpath)],
            cwd=str(_BRAIN_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {
            "saved_file": str(fpath),
            "indexed": False,
            "note": "File saved, but `openkb add` timed out (LLM compile took >5min). Re-run later.",
        }

    if proc.returncode != 0:
        return {
            "saved_file": str(fpath),
            "indexed": False,
            "note": f"openkb add failed: {proc.stderr[:500] or proc.stdout[:500]}",
        }
    # openkb may exit 0 even when a compile stage errored (it keeps the partial wiki).
    # Surface a rate-limit / compile failure honestly instead of reporting success.
    out = (proc.stdout or "") + (proc.stderr or "")
    if "Compilation failed" in out or "RateLimitError" in out:
        return {
            "saved_file": str(fpath),
            "indexed": False,
            "note": "File saved, but the LLM compile failed (likely a rate limit on the free model). The .md is in brain/raw and will index on retry.",
            "output": out[-1000:],
        }
    return {"saved_file": str(fpath), "indexed": True, "output": proc.stdout[-1000:]}


@router.get("/status")
def brain_status():
    inited = (_BRAIN_DIR / ".openkb").exists()
    raw = sorted((_BRAIN_DIR / "raw").glob("*.md")) if (_BRAIN_DIR / "raw").exists() else []
    return {
        "brain_dir": str(_BRAIN_DIR),
        "initialized": inited,
        "openkb_available": _have_openkb(),
        "raw_count": len(raw),
    }


def _have_openkb() -> bool:
    from shutil import which
    return which("openkb") is not None
