"""Content pipeline: the hero product flow.

Paste article text / image notes / video notes + target platforms:
  1. prompt-engineer turns the raw material into per-platform prompts
  2. content-producer turns those prompts into finished, platform-ready content

Two agents chained. Credits are charged per agent and summed.
"""

from __future__ import annotations

from backend.agents import get_agent, run_agent
from backend.billing import charge, InsufficientCredits
from backend.db import User, Usage
from backend.llm import LLMClient
from sqlmodel import Session

# Content Studio stage-2 (content-producer) model per quality/cost mode:
#   economic  -> current cheap pin (or-llama33) — same as the agent default
#   balanced  -> or-sonnet46 (Claude Sonnet 4.6) for better voice/copy
#   quality   -> or-opus (Claude Opus 4.8) for top-tier social copy
# prompt-engineer (stage 1) stays pinned on or-qwen37 regardless of mode.
CONTENT_PRODUCER_MODEL_BY_MODE = {
    "economic": "or-llama33",
    "mixed": "or-sonnet46",
    "balanced": "or-sonnet46",
    "high": "or-opus",
    "quality": "or-opus",
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


def run_content_pipeline(
    session: Session,
    user: User,
    raw_material: str,
    platforms: list[str],
    llm: LLMClient,
    mode: str | None = None,
    output_mode: str = "content",
) -> dict:
    pe = get_agent("prompt-engineer")
    cp = get_agent("content-producer")
    if pe is None or cp is None:
        raise RuntimeError("Pipeline agents missing")

    norm_mode = _normalize_mode(mode)
    cp_model = CONTENT_PRODUCER_MODEL_BY_MODE.get(norm_mode) if norm_mode else None

    # Prompts-only: stage 1, no content generation.
    if output_mode == "prompts":
        stage1_input = (
            f"Source material:\n\"\"\"\n{raw_material}\n\"\"\"\n\n"
            f"Produce generation prompts for these platforms: {', '.join(platforms)}."
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
        )
        text, t1i, t1o, c1 = run_agent(rp, user_msg, llm, override_mode=norm_mode)
        charge(session, user, "content-pipeline", c1, t1i, t1o)
        return {
            "prompts": "",
            "content": text,
            "credits_used": c1,
            "remaining_credits": user.credits if user else 0,
        }

    # Content+Media (default): stage 1 prompts -> stage 2 finished content.
    stage1_input = (
        f"Source material:\n\"\"\"\n{raw_material}\n\"\"\"\n\n"
        f"Produce generation prompts for these platforms: {', '.join(platforms)}."
    )
    prompts_text, t1i, t1o, c1 = run_agent(pe, stage1_input, llm)

    stage2_input = (
        f"Generated prompts:\n\"\"\"\n{prompts_text}\n\"\"\"\n\n"
        f"Now produce the finished, platform-ready content for: {', '.join(platforms)}."
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
