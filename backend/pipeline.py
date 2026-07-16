"""Content pipeline: the hero product flow.

Paste article text / image notes / video notes + target platforms:
  1. prompt-engineer turns the raw material into per-platform prompts
  2. content-producer turns those prompts into finished, platform-ready content

Two agents chained. Credits are charged per agent and summed.
"""

from __future__ import annotations

import json

from backend.agents import get_agent, run_agent
from backend.billing import charge, InsufficientCredits
from backend.db import (
    User,
    Usage,
    ContentBrief,
    ContentOutput,
    get_or_create_dev_user,
)
from backend.llm import LLMClient
from sqlmodel import Session, select

# Content Studio stage-2 (content-producer) model per quality/cost mode (Anthropic-free):
#   economic  -> or-llama33 (cheap bulk copy)
#   mixed/balanced -> or-qwen37 (strong, cheap voice/copy)
#   high/quality -> or-aion3 (Aion storytelling model for top-tier narrative copy)
# prompt-engineer (stage 1) stays pinned on or-qwen37 regardless of mode.
CONTENT_PRODUCER_MODEL_BY_MODE = {
    "economic": "or-llama33",
    "mixed": "or-qwen37",
    "balanced": "or-qwen37",
    "high": "or-aion3",
    "quality": "or-aion3",
}

# Map Content Studio platform labels to the repurposer's channel ids.
_REPURPOSER_CHANNELS = {
    "Instagram": "instagram",
    "TikTok": "shorts_tiktok",
    "LinkedIn": "linkedin",
    "X": "x",
    "YouTube": "youtube",
    "Facebook": "facebook",
}


def _normalize_mode(mode: str | None) -> str | None:
    """Map the frontend toggle onto our canonical mode keys."""
    if mode in ("economic", "mixed", "balanced"):
        return "economic" if mode == "economic" else "balanced"
    if mode in ("high", "quality"):
        return "quality"
    return None


def _resolve_user(session: Session, user: User | None) -> User | None:
    """Return the real user, or a synthetic dev user in REQUIRE_LOGIN=false mode
    so Repurpose history persists and can be shown even in dev-bypass."""
    if user is not None:
        return user
    return get_or_create_dev_user(session)


def run_content_pipeline(
    session: Session,
    user: User,
    raw_material: str,
    platforms: list[str],
    llm: LLMClient,
    mode: str | None = None,
    output_mode: str = "content",
    urls: list[str] | None = None,
    instructions: str = "",
) -> dict:
    pe = get_agent("prompt-engineer")
    cp = get_agent("content-producer")
    if pe is None or cp is None:
        raise RuntimeError("Pipeline agents missing")

    # Fetch any supplied URLs and append their readable text to the material.
    fetched = ""
    if urls:
        from backend.url_reader import read_urls
        fetched = read_urls(urls)
    if fetched:
        raw_material = (
            f"{raw_material}\n\n"
            f"=== Content read from the provided URLs ===\n{fetched}"
        ).strip()

    # Explicit guidance, kept separate from the source so it's read as commands
    # rather than as text to preserve.
    _instructions_block = (
        f"\n\nEXPLICIT INSTRUCTIONS (you MUST follow these, they are not source content):\n"
        f"\"\"\"\n{instructions.strip()}\n\"\"\""
        if instructions and instructions.strip()
        else ""
    )

    norm_mode = _normalize_mode(mode)
    cp_model = CONTENT_PRODUCER_MODEL_BY_MODE.get(norm_mode) if norm_mode else None

    # Prompts-only: stage 1, no content generation.
    if output_mode == "prompts":
        stage1_input = (
            f"Source material:\n\"\"\"\n{raw_material}\n\"\"\"\n\n"
            f"Produce generation prompts for these platforms: {', '.join(platforms)}."
            f"{_instructions_block}"
        )
        prompts_text, t1i, t1o, c1 = run_agent(pe, stage1_input, llm)
        total_credits = c1
        charge(session, user, "content-pipeline", total_credits, t1i, t1o)
        return {
            "prompts": prompts_text,
            "content": "",
            "credits_used": total_credits,
            "remaining_credits": user.credits if user else 0,
        }

    # Repurpose: delegate to the Fusion repurposer agent (rich multi-platform +
    # media suggestions + short-video script package). Channels map to its ids.
    if output_mode == "repurpose":
        rp = get_agent("content-repurposer")
        if rp is None:
            raise RuntimeError("Repurposer agent missing")
        channels = [
            _REPURPOSER_CHANNELS[p] for p in platforms if p in _REPURPOSER_CHANNELS
        ] or list(_REPURPOSER_CHANNELS.values())
        user_msg = (
            f"Audience: general\nBrand voice/tone: match the source's own voice\n"
            f"Produce outputs for these platforms ONLY: {', '.join(channels)}.\n"
            f"If 'shorts_tiktok' is selected, also produce the script package and "
            f"media_suggestions.\n\n"
            f"ARTICLE / ESSAY:\n\"\"\"\n{raw_material}\n\"\"\""
            f"{_instructions_block}"
        )
        text, t1i, t1o, c1 = run_agent(rp, user_msg, llm, override_mode=norm_mode)
        charge(session, user, "content-pipeline", c1, t1i, t1o)

        # Persist a brief + per-channel outputs (richer history than raw text).
        brief_id = None
        effective_user = _resolve_user(session, user)
        if effective_user is not None:
            brief_id = _persist_repurpose(
                session, effective_user.id, raw_material, channels, text
            )

        return {
            "prompts": "",
            "content": text,
            "credits_used": c1,
            "remaining_credits": user.credits if user else 0,
            "brief_id": brief_id,
        }

    # Content+Media (default): stage 1 prompts -> stage 2 finished content.
    stage1_input = (
        f"Source material:\n\"\"\"\n{raw_material}\n\"\"\"\n\n"
        f"Produce generation prompts for these platforms: {', '.join(platforms)}."
        f"{_instructions_block}"
    )
    prompts_text, t1i, t1o, c1 = run_agent(pe, stage1_input, llm)

    stage2_input = (
        f"Generated prompts:\n\"\"\"\n{prompts_text}\n\"\"\"\n\n"
        f"Now produce the finished, platform-ready content for: {', '.join(platforms)}."
        f"{_instructions_block}"
    )
    content_text, t2i, t2o, c2 = run_agent(cp, stage2_input, llm, override_model=cp_model)

    total_credits = c1 + c2
    charge(session, user, "content-pipeline", total_credits, t1i + t2i, t1o + t2o)

    return {
        "prompts": prompts_text,
        "content": content_text,
        "credits_used": total_credits,
        "remaining_credits": user.credits if user else 0,
    }


def _persist_repurpose(
    session: Session,
    user_id: int,
    raw_material: str,
    channels: list[str],
    text: str,
) -> int | None:
    """Parse the repurposer's JSON result and persist a ContentBrief + per-channel
    ContentOutput rows. Returns the brief id, or None if the result isn't JSON."""
    try:
        data = json.loads(text)
        parsed = True
    except json.JSONDecodeError:
        data = {"raw": text}
        parsed = False
    if not parsed:
        return None

    brief = ContentBrief(
        user_id=user_id,
        source_title="",
        source_text=raw_material[:4000],
        channels=",".join(channels),
        tone="match the source's own voice",
        audience="general",
        brief_json=json.dumps(data.get("brief", {}), ensure_ascii=False),
    )
    session.add(brief)
    session.commit()
    session.refresh(brief)

    model = "fusion:or-aion3"
    for ch in channels:
        block = data.get("posts", {}).get(ch)
        if block:
            session.add(ContentOutput(
                brief_id=brief.id, user_id=user_id, channel=ch,
                variant_index=0, content_json=json.dumps(block, ensure_ascii=False),
                model=model,
            ))
    if "script" in data:
        session.add(ContentOutput(
            brief_id=brief.id, user_id=user_id, channel="script",
            content_json=json.dumps(data["script"], ensure_ascii=False), model=model,
        ))
    if "media_suggestions" in data:
        session.add(ContentOutput(
            brief_id=brief.id, user_id=user_id, channel="media",
            content_json=json.dumps(data["media_suggestions"], ensure_ascii=False),
            model=model,
        ))
    session.commit()
    return brief.id
