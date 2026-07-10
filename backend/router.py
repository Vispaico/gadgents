"""Fusion-like model router over *our own* catalog (OpenRouter + OpenAI + Ollama).

Design inspired by OpenRouter Fusion (https://openrouter.ai/docs/guides/features/plugins/fusion):
Fusion runs a *panel* of models in parallel and a *judge* that compares their answers
and returns structured analysis, which a final model turns into the answer. We support
the same idea (opt-in, for hard tasks) but with our own curated models and cost control.

Two usage paths:
1. Single-model selection by MODE or pinned model_id (default, cheap). Modes:
   - "high"     -> High Quality: frontier models, used for hard/nuanced tasks.
   - "mixed"    -> Mixed: not expensive, still high-quality output (default).
   - "economic" -> Very Economic: cheapest tier, fine for summaries/templated work.
2. Fusion (panel + judge): when fusion=True, a panel answers in parallel and a judge
   synthesizes the final answer. Cost is higher (N panel calls + judge); only use when
   being wrong is costly.

Provider strategy (cost control):
  OpenRouter = main catalog (many models, free daily quota).
  OpenAI     = specific high-quality models, free daily quota on Tier 2/3.
  Ollama     = free local fallback.
"""

from dataclasses import dataclass
from typing import Optional

from backend.config import ProviderName, openai_model_ids, openrouter_model_ids
from backend.llm import LLMClient, OpenAIChatMessage

# ---------------------------------------------------------------------------
# Our model catalog. Each entry is one provider/model pair with a cost tier and
# the modes it serves. Add/remove freely; these are OUR models.
# ---------------------------------------------------------------------------
@dataclass
class ModelEntry:
    id: str
    provider: ProviderName
    model: str
    tier: str            # quality | balanced | fast (raw cost/quality posture)
    modes: list[str]     # which selection modes may resolve to this model
    context_tokens: int
    description: str


# Resolve provider model ids from settings (env-overridable). Done once at import so
# the catalog reflects whatever exact names are in .env.
OA = openai_model_ids()
OR = openrouter_model_ids()

MODEL_CATALOG: list[ModelEntry] = [
    # ---- OpenRouter: frontier / quality ----
    ModelEntry("or-opus", "openrouter", OR["opus"], "quality",
                ["high", "mixed"], 200_000,
                "Top reasoning + writing. Use as High Quality judge or hard tasks."),
    ModelEntry("or-sonnet5", "openrouter", OR["sonnet5"], "quality",
                ["high", "mixed"], 200_000, "Strong general quality, lower cost than Opus."),
    ModelEntry("or-sonnet46", "openrouter", OR["sonnet46"], "balanced",
                ["mixed", "economic"], 200_000, "Balanced quality/cost; great Mixed default."),
    ModelEntry("or-kimi", "openrouter", OR["kimi"], "quality",
                ["high", "mixed"], 128_000, "Large reasoning model, strong long-context."),
    ModelEntry("or-ds-pro", "openrouter", OR["ds_pro"], "quality",
                ["high", "mixed"], 128_000, "DeepSeek pro reasoning tier."),
    ModelEntry("or-nex", "openrouter", OR["nex"], "quality",
                ["high"], 128_000, "Nex pro reasoning model."),

    # ---- OpenRouter: balanced workhorses ----
    ModelEntry("or-qwen37", "openrouter", OR["qwen37"], "balanced",
                ["mixed", "economic"], 128_000, "Qwen large; strong general help, cheap."),
    ModelEntry("or-qwen36", "openrouter", OR["qwen36"], "balanced",
                ["mixed", "economic"], 128_000, "Qwen MoE, very cheap for its size."),
    ModelEntry("or-qwen35", "openrouter", OR["qwen35"], "balanced",
                ["mixed", "economic"], 128_000, "Qwen plus, stable."),
    ModelEntry("or-glm", "openrouter", OR["glm"], "balanced",
                ["mixed", "economic"], 128_000, "GLM general model."),
    ModelEntry("or-hy3", "openrouter", OR["hy3"], "balanced",
                ["mixed", "economic"], 128_000, "Tencent Hunyuan v3."),
    ModelEntry("or-nemotron", "openrouter", OR["nemotron"], "balanced",
                ["mixed", "economic"], 128_000, "NVIDIA Nemotron large MoE."),
    ModelEntry("or-mimo", "openrouter", OR["mimo"], "balanced",
                ["mixed", "economic"], 128_000, "Xiaomi Mimo pro."),

    # ---- OpenRouter: fast / Very Economic ----
    ModelEntry("or-haiku", "openrouter", OR["haiku"], "fast",
                ["economic", "mixed"], 200_000, "Fast, cheap Claude for light work."),
    ModelEntry("or-llama33", "openrouter", OR["llama33"], "fast",
                ["economic"], 131_072, "Summaries + short posts from long articles/essays."),
    ModelEntry("or-ds-flash", "openrouter", OR["ds_flash"], "fast",
                ["economic"], 128_000, "Cheap, fast DeepSeek flash."),
    ModelEntry("or-ds-flash-free", "openrouter", OR["ds_flash_free"], "fast",
                ["economic"], 128_000, "Free DeepSeek flash tier (rate-limited)."),
    ModelEntry("or-owl", "openrouter", OR["owl"], "fast",
                ["economic"], 128_000, "Free OpenRouter alpha model (capabilities unknown)."),

    # ---- OpenAI: free daily quota on Tier 2/3. Model ids resolved from .env. ----
    ModelEntry("oa-sol", "openai", OA["sol"], "quality",
                ["high", "mixed"], 400_000, "OpenAI flagship (1M group). Use for hard tasks."),
    ModelEntry("oa-terra", "openai", OA["terra"], "quality",
                ["high", "mixed"], 400_000, "OpenAI large flagship (10M group)."),
    ModelEntry("oa-codex", "openai", OA["codex"], "quality",
                ["high", "mixed"], 400_000, "OpenAI coding/reasoning model."),
    ModelEntry("oa-luna", "openai", OA["luna"], "balanced",
                ["mixed", "economic"], 400_000, "OpenAI balanced (10M group); Mixed default."),
    ModelEntry("oa-mini", "openai", OA["mini"], "fast",
                ["economic", "mixed"], 400_000, "OpenAI mini; cheap."),
    ModelEntry("oa-nano", "openai", OA["nano"], "fast",
                ["economic"], 400_000, "OpenAI nano; cheapest."),

    # ---- Ollama: local free fallback ----
    ModelEntry("local-ollama", "ollama", "qwen3.5:latest", "fast",
                ["economic"], 32_000, "On-device fallback, no API cost."),
]

_BY_ID: dict[str, ModelEntry] = {m.id: m for m in MODEL_CATALOG}

_MODE_ORDER = ["high", "mixed", "economic"]


def list_models() -> list[ModelEntry]:
    return list(MODEL_CATALOG)


def get_model(model_id: str) -> Optional[ModelEntry]:
    return _BY_ID.get(model_id)


# Preferred cost tier per selection mode (used to pick the default model).
_MODE_TIER: dict[str, str] = {"high": "quality", "mixed": "balanced", "economic": "fast"}


def recommend(goal: str = "mixed") -> ModelEntry:
    """Pick the default single model for a mode: high | mixed | economic."""
    mode = goal if goal in _MODE_ORDER else "mixed"
    preferred_tier = _MODE_TIER[mode]
    # First: a model that serves this mode AND matches the preferred tier.
    for entry in MODEL_CATALOG:
        if mode in entry.modes and entry.tier == preferred_tier:
            return entry
    # Then: any model serving this mode.
    for entry in MODEL_CATALOG:
        if mode in entry.modes:
            return entry
    # Fallback: first mixed model.
    for entry in MODEL_CATALOG:
        if "mixed" in entry.modes:
            return entry
    return MODEL_CATALOG[0]


def route(
    llm: LLMClient,
    messages: list[OpenAIChatMessage],
    goal: str = "mixed",
    model_id: Optional[str] = None,
    fusion: bool = False,
    panel: Optional[list[str]] = None,
    judge: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
):
    """Select a model (or run fusion) and return (text, model_id_used).

    With fusion=True, `panel` (list of model ids, default High Quality panel) answers
    in parallel and `judge` (model id) synthesizes a final answer from their outputs.
    """
    if not fusion:
        entry = get_model(model_id) if model_id else recommend(goal)
        if entry is None:
            entry = recommend(goal)
        result = llm.complete_targeted(
            entry.provider, entry.model, messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return result.text, entry.id

    return _run_fusion(
        llm, messages, panel=panel, judge=judge,
        temperature=temperature, max_tokens=max_tokens,
    )


# Default Fusion panel + judge per mode.
_FUSION_PRESETS: dict[str, dict] = {
    "high": {
        "panel": ["or-opus", "or-kimi", "or-ds-pro", "oa-sol"],
        "judge": "or-opus",
    },
    "mixed": {
        "panel": ["or-sonnet46", "or-qwen37", "oa-luna"],
        "judge": "or-sonnet5",
    },
    "economic": {
        "panel": ["or-ds-flash-free", "or-haiku", "oa-nano"],
        "judge": "or-haiku",
    },
}


def _run_fusion(
    llm: LLMClient,
    messages: list[OpenAIChatMessage],
    panel: Optional[list[str]],
    judge: Optional[str],
    temperature: float,
    max_tokens: int,
) -> tuple[str, str]:
    mode = "mixed"
    panel_ids = panel or _FUSION_PRESETS[mode]["panel"]
    judge_id = judge or _FUSION_PRESETS[mode]["judge"]

    answers: list[tuple[str, str]] = []
    for pid in panel_ids:
        entry = get_model(pid)
        if entry is None:
            continue
        try:
            res = llm.complete_targeted(
                entry.provider, entry.model, messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            answers.append((entry.id, res.text))
        except Exception:
            # Skip a failed panel member rather than aborting the whole fusion.
            continue

    if not answers:
        raise RuntimeError("Fusion panel: all models failed")

    judge_entry = get_model(judge_id)
    if judge_entry is None:
        judge_entry = get_model(answers[0][0])
    synthesis_prompt = _build_judge_prompt(answers)
    judge_messages = messages + [{"role": "user", "content": synthesis_prompt}]
    result = llm.complete_targeted(
        judge_entry.provider, judge_entry.model, judge_messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    return result.text, f"fusion:{judge_entry.id}"


def _build_judge_prompt(answers: list[tuple[str, str]]) -> str:
    parts = ["You are the judge in a multi-model panel. Several models answered the same "
             "request. Compare them and write ONE final, improved answer. In your reasoning, "
             "report JSON: consensus (points most models agree on), contradictions, and unique "
             "insights. Then give the final answer.\n"]
    for label, text in answers:
        parts.append(f"\n--- Model: {label} ---\n{text}")
    return "\n".join(parts)
