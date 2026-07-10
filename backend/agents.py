"""Agent registry: plain data objects (system prompt + model hint + optional tool).

Agents self-register via the :func:`agent` factory, so adding a new production-ready
agent needs no router changes. The routes read ``REGISTRY`` directly (only agents with
``production_ready=True`` are exposed). Teams/coordination (e.g. the content pipeline)
are just named flows built on top of individual agents. No orchestration framework.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from backend.llm import LLMClient, OpenAIChatMessage


# Global registry, populated by the agent() factory below.
REGISTRY: dict[str, "AgentDef"] = {}


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
    # Cost-control: catalog id from backend.router.MODEL_CATALOG (e.g. "balanced-openrouter").
    # When set, the agent's calls are pinned to that exact model/provider via the fusion
    # router (deterministic cost). When None, falls back to recommend("balanced").
    router_model: Optional[str] = None
    # When True the agent is exposed by the list/chat routes. Keep False while a new
    # agent is in development; flip to True to ship it (auto-wired, no router edit).
    production_ready: bool = True


def agent(production_ready: bool = True, **fields) -> AgentDef:
    """Factory + registrar. Builds an AgentDef, registers it, returns it.

    ``production_ready`` controls whether the agent is exposed by the list/chat routes.
    """
    if "id" not in fields:
        raise ValueError("agent() requires an 'id' field")
    if fields["id"] in REGISTRY:
        raise ValueError(f"Agent id already registered: {fields['id']}")
    definition = AgentDef(production_ready=production_ready, **fields)
    REGISTRY[definition.id] = definition
    return definition


def get_agent(agent_id: str) -> Optional[AgentDef]:
    return REGISTRY.get(agent_id)


# ---------------------------------------------------------------------------
# Hero agent 1: Prompt Engineer
#   Turns pasted article text / image descriptions / video notes + target
#   platforms into clean, ready-to-use generation prompts.
# ---------------------------------------------------------------------------
agent(
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
    router_model="or-qwen37",  # cheap, high-quality via OpenRouter (Mixed default)
)

# ---------------------------------------------------------------------------
# Hero agent 2: Content Producer
#   Takes a generated prompt (or the raw brief) and produces platform-ready
#   content: captions, scripts, hashtags, posts.
# ---------------------------------------------------------------------------
agent(
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
    router_model="or-llama33",  # llama-3.3 for short posts/summaries out of long text
)

# Utility agent shipped as a real, working example.
agent(
    id="coder",
    name="Coder",
    description="Answers coding questions and writes small code snippets.",
    system_prompt="You are a concise senior software engineer. Provide working code and short explanations.",
    base_credits=5,
    router_model="oa-codex",  # OpenAI gpt-5.1-codex (coding model, free daily quota)
)


def list_production_agents() -> list[AgentDef]:
    """Agents currently exposed to the frontend / API."""
    return [a for a in REGISTRY.values() if a.production_ready]


def run_agent(agent: AgentDef, user_input: str, llm: LLMClient) -> "tuple[str, int, int, int]":
    """Returns (text, tokens_in, tokens_out, credits_estimate)."""
    messages: list[OpenAIChatMessage] = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": user_input},
    ]
    # Route through the fusion router for deterministic cost control: pin the agent's
    # catalog model when set, otherwise let the router pick a balanced default.
    from backend.router import route

    result, _used_id = route(llm, messages, model_id=agent.router_model)
    # Credit estimate: base + token cost (1 credit per ~1k tokens combined).
    token_cost = max(1, (result.tokens_in + result.tokens_out) // 1000)
    credits = agent.base_credits + token_cost
    return result.text, result.tokens_in, result.tokens_out, credits
