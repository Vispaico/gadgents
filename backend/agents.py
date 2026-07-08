"""Minimal agent primitive: a system prompt + model hint + optional tools.

Agents are plain data; the router turns a user message into an LLM completion.
No orchestration framework needed. Teams/coordination are just named flows
pipeline.py) built on top of individual agents.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.llm import LLMClient, OpenAIChatMessage


@dataclass
class AgentDef:
    id: str
    name: str
    description: str
    system_prompt: str
    model: Optional[str] = None
    # Optional structured tool the agent can call against raw input (e.g. parse upload).
    input_tool: Optional[Callable[[dict], str]] = None
    # credits charged per chat call (covers model + tool cost); token-based delta applied after.
    base_credits: int = 5


# ---------------------------------------------------------------------------
# Hero agent 1: Prompt Engineer
#   Turns pasted article text / image descriptions / video notes + target
#   platforms into clean, ready-to-use generation prompts.
# ---------------------------------------------------------------------------
PROMPT_ENGINEER = AgentDef(
    id="prompt-engineer",
    name="Prompt Engineer",
    description="Turns your article, image or video idea into perfect prompts for any platform.",
    system_prompt=(
        "You are a senior prompt engineer. The user gives you raw material: article text, "
        "image references, video notes, or a loose idea, plus the platforms they want content for "
        "(e.g. Instagram, TikTok, LinkedIn, X, YouTube). Produce a set of precise, self-contained "
        "generation prompts that another agent or model can use directly. For each platform return: "
        "(1) a one-line objective, (2) the prompt text, (3) recommended style/format notes. Be "
        "specific about framing, tone, aspect ratio, and length. Do not invent facts from the source."
    ),
    base_credits=5,
)

# ---------------------------------------------------------------------------
# Hero agent 2: Content Producer
#   Takes a generated prompt (or the raw brief) and produces platform-ready
#   content: captions, scripts, hashtags, posts.
# ---------------------------------------------------------------------------
CONTENT_PRODUCER = AgentDef(
    id="content-producer",
    name="Content Producer",
    description="Converts a brief or prompt into finished, platform-ready social content.",
    system_prompt=(
        "You are a content producer for social media. Given a prompt or a short brief, produce "
        "finished, platform-ready content. Always output, per requested platform: the caption/post "
        "copy, a hook (first line), 8-15 relevant hashtags, and a 1-sentence posting tip. Match the "
        "brand voice implied by the brief. Keep copy native to each platform's conventions."
    ),
    base_credits=5,
)

# Utility agents shipped as real, working examples.
CODER = AgentDef(
    id="coder",
    name="Coder",
    description="Answers coding questions and writes small code snippets.",
    system_prompt="You are a concise senior software engineer. Provide working code and short explanations.",
    model="openai/gpt-4.1-mini" if False else None,
    base_credits=5,
)


REGISTRY: dict[str, AgentDef] = {
    a.id: a for a in (PROMPT_ENGINEER, CONTENT_PRODUCER, CODER)
}


def get_agent(agent_id: str) -> Optional[AgentDef]:
    return REGISTRY.get(agent_id)


def run_agent(agent: AgentDef, user_input: str, llm: LLMClient) -> "tuple[str, int, int, int]":
    """Returns (text, tokens_in, tokens_out, credits_estimate)."""
    messages: list[OpenAIChatMessage] = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": user_input},
    ]
    result = llm.complete(messages, model=agent.model)
    # Credit estimate: base + token cost (1 credit per ~1k tokens combined).
    token_cost = max(1, (result.tokens_in + result.tokens_out) // 1000)
    credits = agent.base_credits + token_cost
    return result.text, result.tokens_in, result.tokens_out, credits
