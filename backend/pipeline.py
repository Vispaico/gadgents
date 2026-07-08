"""Content pipeline: the hero product flow.

Paste article text / image notes / video notes + target platforms:
  1. prompt-engineer turns the raw material into per-platform prompts
  2. content-producer turns those prompts into finished, platform-ready content

Two agents chained. Credits are charged per agent and summed.
"""

from backend.agents import get_agent, run_agent
from backend.billing import charge, InsufficientCredits
from backend.db import User, Usage
from backend.llm import LLMClient
from sqlmodel import Session


def run_content_pipeline(
    session: Session,
    user: User,
    raw_material: str,
    platforms: list[str],
    llm: LLMClient,
) -> dict:
    pe = get_agent("prompt-engineer")
    cp = get_agent("content-producer")
    if pe is None or cp is None:
        raise RuntimeError("Pipeline agents missing")

    stage1_input = (
        f"Source material:\n\"\"\"\n{raw_material}\n\"\"\"\n\n"
        f"Produce generation prompts for these platforms: {', '.join(platforms)}."
    )
    prompts_text, t1i, t1o, c1 = run_agent(pe, stage1_input, llm)

    stage2_input = (
        f"Generated prompts:\n\"\"\"\n{prompts_text}\n\"\"\"\n\n"
        f"Now produce the finished, platform-ready content for: {', '.join(platforms)}."
    )
    content_text, t2i, t2o, c2 = run_agent(cp, stage2_input, llm)

    total_credits = c1 + c2
    try:
        charge(session, user, "content-pipeline", total_credits, t1i + t2i, t1o + t2o)
    except InsufficientCredits:
        raise

    return {
        "prompts": prompts_text,
        "content": content_text,
        "credits_used": total_credits,
        "remaining_credits": user.credits,
    }
