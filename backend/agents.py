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
    # router (deterministic cost). When None, falls back to `mode`.
    router_model: Optional[str] = None
    # Selection mode used when router_model is None: high | mixed | economic.
    mode: str = "mixed"
    # Multi-model: when True the agent runs through the Fusion router (panel + judge)
    # using `fusion_panel` (catalog model ids) and `fusion_judge` (catalog model id).
    fusion: bool = False
    fusion_panel: Optional[list] = None
    fusion_judge: Optional[str] = None
    # When True the agent is exposed by the list/chat routes. Keep False while a new
    # agent is in development; flip to True to ship it (auto-wired, no router edit).
    production_ready: bool = True
    # When False the agent still runs (e.g. powering Content Studio) but its card is
    # hidden from the Bots page so users aren't exposed to raw stages of a flow.
    show_in_bots: bool = True


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
    show_in_bots=False,  # stage 1 of Content Studio; surfaced there, not as a bare bot
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
    show_in_bots=False,  # stage 2 of Content Studio; surfaced there, not as a bare bot
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

# ---------------------------------------------------------------------------
# Agent 1 (next build): Personal Secretary & Planner
#   A stateful, learning secretary. Stateless chat wrapper here returns a
#   STRUCTURED plan (tasks, time_blocks, reminders, escalation) that the
#   proactive subsystem (DB models) later drives. Reads user memory when provided.
# ---------------------------------------------------------------------------
PLANNER_SYSTEM_PROMPT = """You are the user's personal secretary and planner, not a calendar app.
You exist because standard planners fail people who "do what comes to mind" and never check
the app. Your job is to make intent become a real, defended day plan, and to keep pushing the
next action back into view until it is done, deferred, or renegotiated.

PERSONALITY & BEHAVIOR
- Be concise, direct, and a little pushy in a helpful way. You protect the user's focus and
  attention like a real secretary would. Don't be passive.
- You respect learned preferences (tone, focus protection, working hours, snooze style). When
  uncertain, act reasonably and note the assumption so you can learn.
- When the user dumps messy intent, you CLARIFY ONLY IF BLOCKED — ask at most one sharp question,
  otherwise propose and let them correct. Never ask a question you can reasonably infer.
- You proactively REPLAN when life interferes (birthday invite, surprise meeting): you reslot,
  don't leave stale blocks. You escalate ignored reminders.

CLASSIFY every captured item into exactly one of:
task | appointment | idea | reference | waiting_on | someday.
Every TASK must get, before entering the plan: a next_action (one concrete step), an estimated
duration_min, and an urgency (1-5) + confidence (1-5). If missing, infer and flag it.

OUTPUT
Always reply with a single JSON object (no prose outside it) of shape:
{
  "inbox": [{"raw": "<text>", "kind": "task|appointment|idea|reference|waiting_on|someday"}],
  "tasks": [{"title": str, "next_action": str, "duration_min": int, "urgency": 1-5,
             "confidence": 1-5, "due": "ISO or null", "project": str|null}],
  "time_blocks": [{"title": str, "start": "ISO", "end": "ISO", "kind":
                   "focus|deep_work|admin|break|disruption", "focus": bool}],
  "reminders": [{"trigger_at": "ISO", "stage": 1-4, "message": str,
                 "channel": "inbox", "escalates_to": "reslot|commit|drop"}],
  "replan_note": str,            // what you changed and why
  "learned": [{"key": str, "value": str, "confidence": 1-5}], // new preferences you inferred
  "ask": str|null                // one clarifying question if truly blocked, else null
}
Rules: protect at least one deep_work/focus block per working day. Keep blocks realistic
(use the user's working hours from memory; default 09:00-18:00). A task with no block is a
risk — always propose a slot. Escalation stages: 1 soft nudge, 2 stronger nudge,
3 "snooze or commit?" prompt, 4 auto-reslot if ignored. Only output valid JSON.
"""

agent(
    id="personal-planner",
    name="Personal Secretary & Planner",
    description="Organizes your goals, todos and surprises into a defended day plan with escalating reminders. Learns your working style.",
    system_prompt=PLANNER_SYSTEM_PROMPT,
    base_credits=8,
    router_model=None,  # None -> router uses mode (we send "high" for planning)
    mode="high",  # planning/recovery needs a strong model
)

# ---------------------------------------------------------------------------
# Agent 2 (next build): Summarizer / vibe-preserving repurposer (MULTI-MODEL).
#   Turns a long article/essay/URL text into: a structured brief, platform-ready
#   social posts (LinkedIn, FB, X, IG, YT, Shorts/TikTok), image/media suggestions,
#   and a scene-annotated short video script package. Runs in Fusion mode: a panel
#   of our models (DeepSeek pro analysis + GPT-5.x JSON brief + Claude writing +
#   Llama bulk variants) answers in parallel, a Claude judge synthesizes.
#   Later it can chain its brief into prompt-engineer -> content-producer for polish.
# ---------------------------------------------------------------------------
REPURPOSER_SYSTEM_PROMPT = """You are a senior content strategist + copywriter + video producer.
You turn a long article, essay, or pasted text into multi-platform social content while
PRESERVING the original's vibe, voice, and gist. You never invent facts, stats, case
studies, or quotes that are not in the source.

You are operating as the JUDGE in a multi-model panel: several models already answered the
same request. Their raw answers are in the conversation. Your job is to synthesize ONE
final, coherent result in the exact JSON shape below — reconcile contradictions, keep the
best angles, and keep the source's voice.

Always reply with a single JSON object (no prose outside it):

{
  "brief": {
    "tldr": "one sentence, max 30 words",
    "key_points": ["5-8 bullets, each <=25 words"],
    "pain_points": ["3-5 audience pains the source addresses"],
    "insights": ["3-5 non-obvious insights/opinions from the source"],
    "quotes": ["3-7 punchy pull-quote lines"],
    "cta_ideas": ["3-5 call-to-action ideas"],
    "visual_themes": ["3-5 visual/mood directions"]
  },
  "posts": {
    "linkedin": [{"hook": str, "body": str, "cta": str, "hashtags": [str]}],
    "facebook": [{"body": str, "image_idea": str, "cta": str}],
    "x": [{"text": str, "hashtags": [str]}],
    "instagram": [{"caption": str, "hashtags": [str]}],
    "youtube": [{"title": str, "description": str, "hashtags": [str]}],
    "shorts_tiktok": [{"hook": str, "caption": str}]
  },
  "media_suggestions": [
    {"post_ref": str, "image_prompt": str, "broll_keywords": [str], "overlay_text": str}
  ],
  "script": {
    "title": str,
    "target_duration_sec": int,
    "hook": "first 3-second spoken line",
    "scenes": [
      {"scene": int, "duration_sec": int, "spoken": str,
       "onscreen_text": str, "visual_idea": str, "broll_keywords": [str]}
    ],
    "cta": str
  },
  "notes": "anything uncertain or assumed"
}

RULES
- Cover ONLY the platforms requested by the user; omit absent ones.
- Match the language of the source unless told otherwise.
- Vary hooks/angles across posts; never repeat the same hook.
- Short lines, whitespace, mobile-first. Lead with a strong hook.
- For scripts: hook in first 3s, problem/tension, 2-4 step breakdown, explicit CTA.
- media_suggestions must be concrete, filmable prompts (for Flux/Wan/etc.), not vague.
- Do NOT fabricate. If the source lacks material for a requested output, say so in notes.
- Output valid JSON only.
"""

agent(
    id="content-repurposer",
    name="Content Repurposer (Summarizer + Multi-Platform)",
    description="Summarizes long articles/essays preserving the vibe and repurposes them into platform posts, media suggestions and short video scripts. Multi-model (Fusion).",
    system_prompt=REPURPOSER_SYSTEM_PROMPT,
    base_credits=12,
    # Multi-model: analysis (DeepSeek pro), structured JSON brief (OpenAI GPT-5.x),
    # narrative voice (Aion-3.0-Mini), and cheap bulk variants (Llama 3.3 — still strong
    # for repurposing). Anthropic-free. Judge (DeepSeek pro) synthesizes the final result.
    fusion=True,
    fusion_panel=["or-ds-pro", "oa-sol", "or-aion3-mini", "or-llama33"],
    fusion_judge="or-ds-pro",
    router_model=None,
    mode="high",
    show_in_bots=False,  # surfaced inside Content Studio's "Repurpose" mode, not as a bare bot
)


# ---------------------------------------------------------------------------
# Agent #3: Lead Finder (ICP-driven public-web lead discovery + fit scoring).
#   A coordinator chain (backend.leads.pipeline), NOT a single chat model. It reuses
#   the user's Scraper discovery/analysis + our Fusion router: stage 1 runs a panel to
#   draft perfect Google search strings, then discovery/audit/scoring run per-domain.
#   production_ready=False until tested on the user's machine (needs live keys +, for
#   Firecrawl mode, the local firecrawl-simple docker). Frontend: chat ICP wizard.
# ---------------------------------------------------------------------------
LEAD_FINDER_SYSTEM_PROMPT = """You are the Lead Finder agent's conversational front end.
You help a user (who is an agency/service provider) define the Ideal Customer Profile for
a lead-search campaign. Ask sharp, sequential questions ONLY if something is genuinely
missing: (1) what they offer/sell, (2) the geography, (3) the target niches/industries and
any exclusions, (4) company size, (5) language. Once you have enough, restate the ICP back
to the user in one tight paragraph and confirm before they run the search.

You do NOT scrape. You only clarify the ICP and feed it to the discovery engine. Keep it
short and practical — this user thinks in niches like "boutique strategy consultancies 10-50
people" or "deep-tech B2B SaaS with unclear messaging". Never invent leads; say when you
need more detail.
"""

agent(
    id="lead-finder",
    name="Lead Finder (ICP Discovery + Fit Scoring)",
    description="Turns your offer + target niche into perfect Google search strings, discovers small excellent-but-invisible firms on the public web, audits their presence, and scores fit with an outreach angle. GDPR-safe (public web only).",
    system_prompt=LEAD_FINDER_SYSTEM_PROMPT,
    base_credits=15,
    router_model="or-qwen37",   # mixed, non-Anthropic; the heavy lifting is in the chain, not here
    mode="mixed",
    production_ready=True,
    show_in_bots=False,  # surfaced as the dedicated "Lead Finder" nav tab, not a bare bot card
)


# ---------------------------------------------------------------------------
# Agent #4: Wan2.2 Image-to-Video Prompt (camera-move-driven one-shot clips).
#   Turns a source image + concept/script/mood into a sequence of Wan2.2-ready
#   image-to-video prompts. Each shot = one ~5s clip with one dominant camera move
#   (from our 50-move vocabulary) so stitched clips form a coherent video. Runs in
#   Fusion: panel covers visual reasoning + structured shot JSON + clean prompt
#   writing, a judge (Claude Opus) synthesizes the final storyboard. Loosely chains
#   off agents 1+2 (the repurposer/Content Studio can feed the concept).
#   The format-structure knowledge (ads/docs/short films) is a tuning-phase hook.
# ---------------------------------------------------------------------------
from backend.wan.prompt_builder import build_system_prompt as _build_wan_system_prompt

agent(
    id="wan-video",
    name="Wan2.2 Video Prompt (Image-to-Video)",
    description="Turns a source image + concept into a sequence of Wan2.2-ready image-to-video prompts (one ~5s clip per shot) using a 50-move camera vocabulary. Multi-model (Fusion).",
    system_prompt=_build_wan_system_prompt(),
    base_credits=12,
    fusion=True,
    # Purpose-tuned for video-prompt generation (creative + structured camera vocabulary):
    # Aion-3.0-Mini leads visual narrative (full aion3 is too slow for the loop), DeepSeek-pro
    # + OpenAI for structure, Llama for variety. Anthropic-free; judge = ds-pro (fast, reliable).
    fusion_panel=["or-aion3-mini", "or-ds-pro", "oa-sol", "or-llama33"],
    fusion_judge="or-ds-pro",
    router_model=None,
    mode="high",
)


# ---------------------------------------------------------------------------
# Agent #6: Editorial AI Studio — a staged content engine (NOT a single chat agent).
#   From one essay it mines ideas -> plans a calendar -> creates platform-native
#   assets (4 versions each) -> humanizes -> quality-scores. Brand voice is a
#   pluggable BrandProfile (adapts to any brand, default = Vispaico). The 6 stage
#   SYSTEM PROMPTS live in PromptTemplate (editable), mirrored here as the agents'
#   defaults. show_in_bots=False: the stages power the Editorial Studio tab, and are
#   orchestrated by backend/editorial.py, not surfaced as bare chat bots.
# ---------------------------------------------------------------------------
from backend.db import _EDITORIAL_STAGE_PROMPTS

agent(
    id="editorial-idea-miner",
    name="Editorial Idea Miner",
    description="Extracts 25-50 publishable ideas (with angles + platform fit) from a source essay.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["idea_miner"],
    base_credits=10,
    router_model="or-opus",  # strong single model; no Fusion needed for mining
    show_in_bots=False,
)

agent(
    id="editorial-strategist",
    name="Editorial Strategist",
    description="Picks the best, most diverse ideas and lays out a 4-week publishing calendar.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["strategist"],
    base_credits=8,
    router_model="or-opus",
    show_in_bots=False,
)

agent(
    id="editorial-creator",
    name="Editorial Creator",
    description="For ONE idea, creates platform-native assets (LinkedIn/FB/IG/X/Newsletter/YT Shorts/Long/Podcast + Quotes/Hooks/Questions/Predictions), 4 versions each.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["creator"],
    base_credits=12,
    # SINGLE-MODEL on purpose: this stage runs once PER ASSET in the per-idea x per-platform
    # loop, so Fusion (4 panel + judge, ~100s) would make a run cost minutes per asset and
    # blow the 20-min guardrail before a single asset commits. A single strong model keeps
    # each Creator call to ~30s while the agent's storytelling SYSTEM PROMPT preserves the
    # Aion-voice output. The Quality/Cost toggle still drives the model (Quality->ds-pro,
    # Balanced->qwen37, Economic->llama33) via _run_stage, so the toggle stays meaningful.
    # (fusion_panel/judge retained for reference only; not used when fusion=False.)
    fusion=False,
    fusion_panel=["or-aion3-mini", "or-qwen37", "oa-luna", "or-llama33"],
    fusion_judge="or-aion3-mini",
    router_model=None,
    mode="high",
    show_in_bots=False,
)

agent(
    id="editorial-humanizer",
    name="Editorial Humanizer",
    description="Strips AI tells (rhythm, cliches, jargon) from each created asset, keeping meaning.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["humanizer"],
    base_credits=8,
    router_model="or-opus",
    show_in_bots=False,
)

agent(
    id="editorial-quality-director",
    name="Editorial Quality Director",
    description="Scores each asset 1-10 across 14 dimensions; rewrites until it hits >=9.5.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["quality_director"],
    base_credits=10,
    # SINGLE-MODEL on purpose: like the Creator, this runs once PER ASSET in the hot loop.
    # Fusion here (~95s) was the other half of the "burn tokens, get no assets" trap. A
    # single strong model (~20-30s) scores/rewrites fast enough that assets commit in real
    # time and a run actually finishes. Toggle still drives the model via _run_stage.
    fusion=False,
    fusion_panel=["or-ds-pro", "oa-sol", "or-qwen37", "or-llama33"],
    fusion_judge="or-ds-pro",
    router_model=None,
    mode="high",
    show_in_bots=False,
)

agent(
    id="editorial-multiplier",
    name="Editorial Multiplier",
    description="Proposes new IP (essays, videos, talks, lead magnets) the brand can spin up next from a finished run.",
    system_prompt=_EDITORIAL_STAGE_PROMPTS["multiplier"],
    base_credits=8,
    router_model="or-opus",
    show_in_bots=False,
)


def list_production_agents() -> list[AgentDef]:
    """Agents currently exposed to the frontend / API."""
    return [a for a in REGISTRY.values() if a.production_ready]


def list_bot_agents() -> list[AgentDef]:
    """Production agents that should appear as cards on the Bots page."""
    return [a for a in list_production_agents() if a.show_in_bots]


def run_agent(
    agent: AgentDef,
    user_input: str,
    llm: LLMClient,
    memory: Optional[str] = None,
    override_mode: Optional[str] = None,
    override_model: Optional[str] = None,
) -> "tuple[str, int, int, int]":
    """Returns (text, tokens_in, tokens_out, credits_estimate).

    `memory` is an optional string of the user's learned preferences, injected so the
    agent adapts over time (the learning layer).
    `override_mode` (high|mixed|economic) lets a caller (e.g. the frontend quality/cost
    toggle) override the agent's default mode for non-pinned, non-fusion routing.
    `override_model` (catalog id) temporarily swaps the agent's pinned model for this
    call only (race-free) — used by the Content Studio to map its stage-2 model per mode."""
    messages: list[OpenAIChatMessage] = [
        {"role": "system", "content": agent.system_prompt},
    ]
    if memory:
        messages.append(
            {"role": "system", "content": f"Learned user preferences so far:\n{memory}"}
        )
    messages.append({"role": "user", "content": user_input})
    # Route through the fusion router. Priority:
    #   1) explicit router_model pin (single model; override_model can swap it),
    #   2) fusion panel + judge (multi-model; if override_mode is set, use that mode's
    #      Fusion preset instead of the agent's tuned panel so the quality/cost toggle
    #      is meaningful even for Fusion agents),
    #   3) mode-based single selection (high/mixed/economic, overridable).
    from backend.router import route, _FUSION_PRESETS

    fusion = agent.fusion
    panel = agent.fusion_panel
    judge = agent.fusion_judge
    goal = override_mode or agent.mode
    if fusion and override_mode in _FUSION_PRESETS:
        # User forced a quality/cost mode: swap to that mode's Fusion preset.
        panel = _FUSION_PRESETS[override_mode]["panel"]
        judge = _FUSION_PRESETS[override_mode]["judge"]

    model_id = override_model or agent.router_model

    result, _used_id = route(
        llm,
        messages,
        model_id=model_id,
        goal=goal,
        fusion=fusion,
        panel=panel,
        judge=judge,
    )
    # `result` is the model text. Estimate tokens from length (~4 chars/token) for the
    # credit cost; combined in/out approximated as the generated text length.
    token_cost = max(1, len(result) // 4000)
    credits = agent.base_credits + token_cost
    return result, 0, 0, credits
