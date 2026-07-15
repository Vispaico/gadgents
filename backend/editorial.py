"""Editorial AI Studio: a staged content engine (agent #6).

From one essay it mines ideas -> plans a calendar -> creates platform-native assets
(4 versions each) that are humanized + quality-scored. Brand voice is injected from a
pluggable BrandProfile so the engine adapts to ANY brand (default = Vispaico). The 6
stage SYSTEM PROMPTS live in PromptTemplate (editable without code edits). Stages 1-5
ship now; the Multiplier (stage 6) is optional.

Orchestration shape (mirrors backend/pipeline.py but with a loop):
    ideas   = Idea Miner(essay + brand)            -> IdeaBank
    plan    = Strategist(ideas + brand)            -> EditorialCalendar
    for idea in plan.selected:
        for platform in selected_platforms:
            raw  = Creator(idea + platform + brand) -> EditorialAsset
            hum  = Humanizer(raw + brand)
            fin  = Quality Director(hum + brand)    -> EditorialAsset (scored)
    multiplier = Multiplier(all assets)   # optional, deferred by default
"""

from __future__ import annotations

import json
import time
from typing import Optional

from backend.agents import get_agent
from backend.billing import charge, InsufficientCredits
from backend.db import (
    User,
    EditorialRun,
    IdeaBank,
    EditorialCalendar,
    EditorialAsset,
    BrandProfile,
    PromptTemplate,
    get_or_create_dev_user,
)
from backend.llm import LLMClient, OpenAIChatMessage
from sqlmodel import Session, select


class EditorialCanceled(Exception):
    """Raised when an editorial run is canceled (by the user or a guardrail) so the
    worker loop can stop cleanly. Distinguished from a real failure at the call site."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        super().__init__(f"Editorial run {run_id} was canceled")


# Platforms the engine can target. The frontend chooses a subset.
EDITORIAL_PLATFORMS = [
    "linkedin",
    "facebook",
    "instagram",
    "x",
    "newsletter",
    "youtube_shorts",
    "youtube_long",
    "podcast",
    "quotes",
    "hooks",
    "questions",
    "predictions",
]

# Extra one-liner counts for the non-post "kinds".
_KIND_COUNTS = {"quotes": 10, "hooks": 20, "questions": 10, "predictions": 10}

# Stage -> agent id (the registry entry). The system prompt is read from
# PromptTemplate (when present) so it stays editable without code changes.
_STAGE_AGENT = {
    "idea_miner": "editorial-idea-miner",
    "strategist": "editorial-strategist",
    "creator": "editorial-creator",
    "humanizer": "editorial-humanizer",
    "quality_director": "editorial-quality-director",
    "multiplier": "editorial-multiplier",
}

# ---------------------------------------------------------------------------
# Run guardrails: keep a runaway Editorial run from burning unbounded tokens.
# ---------------------------------------------------------------------------
# Per-run wall-clock ceiling. A run that exceeds this is auto-aborted (the system
# prompt is long for each stage, so budget generously but not unbounded).
RUN_TIMEOUT_SECONDS = 20 * 60  # 20 minutes

# Hard ceiling on estimated credits for ONE run. Editorial is expensive; this is a
# circuit breaker so a misbehaving chain can never blow the whole balance. Mirrors
# the per-stage estimate in _estimate_credits (base + ~1 per 4000 chars generated).
RUN_MAX_CREDITS = 2000

# In-memory set of run_ids that the user (or the guardrail) has asked to cancel.
# Editorial runs execute on a worker thread; the worker checks this flag between
# stages and after every model call, because a kill of the dev server does NOT stop
# in-flight OpenRouter requests (they keep billing server-side after the client dies).
_CANCELLED: set[int] = set()

# Per-mode max_tokens for each stage. The earlier flat 8000 was a token multiplier:
# every Fusion panel member + the judge each emitted up to 8000 output tokens even
# for small assets. Most stages need far less; the Quality Director (a single asset
# rewrite) is the only place that occasionally needs more.
_STAGE_MAX_TOKENS: dict[str, int] = {
    "idea_miner": 4000,    # 25-50 short ideas as JSON; 4k is plenty (was 6k = slow + costly)
    "strategist": 3000,
    "creator": 3000,       # per-platform asset (4 versions) rarely needs more than 3k
    "humanizer": 2500,
    "quality_director": 3000,  # single-asset rewrite; capped to bound per-asset cost
    "multiplier": 2500,
}


def cancel_run(run_id: int) -> None:
    """Mark a run for cancellation (checked by the worker loop)."""
    _CANCELLED.add(run_id)


def is_canceled(run_id: int) -> bool:
    return run_id in _CANCELLED


def clear_cancel(run_id: int) -> None:
    _CANCELLED.discard(run_id)


def reap_interrupted_runs(session: Session) -> int:
    """On startup, mark any run left in "running" (its worker died with the previous
    process) as failed so it stops showing perpetual "running" in the UI. Without this,
    killing the dev server left the row running forever and the UI polled indefinitely.
    Returns the number of runs reaped."""
    stuck = session.exec(
        select(EditorialRun).where(EditorialRun.status == "running")
    ).all()
    for r in stuck:
        r.status = "failed"
        r.error = (
            "Run was interrupted (server restarted or process killed). "
            "Partial assets, if any, are kept."
        )
        session.add(r)
    if stuck:
        session.commit()
    return len(stuck)


def _stage_system_prompt(session: Session, stage: str) -> str:
    """Editable stage prompt from PromptTemplate, falling back to the agent default."""
    tpl = session.exec(select(PromptTemplate).where(PromptTemplate.stage == stage)).first()
    if tpl and tpl.system_prompt.strip():
        return tpl.system_prompt
    agent_def = get_agent(_STAGE_AGENT[stage])
    return agent_def.system_prompt if agent_def else ""


def _run_stage(
    llm: LLMClient,
    session: Session,
    stage: str,
    user_input: str,
    override_mode: Optional[str] = None,
    run_id: Optional[int] = None,
) -> tuple[str, str]:
    """Run one editorial stage. Uses the editable PromptTemplate as the system prompt
    and routes through Fusion (agents that are fusion=True) honoring the quality/cost
    toggle. Returns (text, model_id_used).

    CRITICAL cost rule: the user's Quality / Balanced / Economic toggle is the SOURCE OF
    TRUTH. The editorial agents hard-pin Opus for single-model stages and default to the
    High Opus Fusion panel, so BOTH the hard pin AND the agent default must be overridden
    here — otherwise "Balanced" silently bills Opus for every stage (the runaway bug).
    Mapping: Quality -> "high" (Opus), Balanced -> "mixed" (NO Opus), Economic -> cheapest.
    The frontend sends Balanced as null/"mixed", so a missing mode defaults to "mixed".
    - Max_tokens is per-stage (not a flat 8000) to bound output tokens per call.
    - Raises EditorialCanceled if the run was canceled or the wall-clock budget blew."""
    from backend.router import route, _FUSION_PRESETS

    if run_id is not None and is_canceled(run_id):
        raise EditorialCanceled(run_id)

    agent_def = get_agent(_STAGE_AGENT[stage])
    system_prompt = _stage_system_prompt(session, stage)
    messages: list[OpenAIChatMessage] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    # The user's toggle drives the whole stage. Balanced (null from the UI) resolves to
    # "mixed", which has NO Opus in either the single-model map or the fusion preset.
    eff_mode = override_mode if override_mode in ("economic", "mixed", "high") else "mixed"
    mt = _STAGE_MAX_TOKENS.get(stage, 4000)

    if agent_def.fusion:
        # Use the matching Fusion preset for the chosen mode. All three keys exist; the
        # "mixed" preset (sonnet46/qwen37/luna, judge sonnet5) contains no Opus.
        preset = _FUSION_PRESETS[eff_mode]
        result, used_id = route(
            llm,
            messages,
            model_id=None,
            goal=eff_mode,
            fusion=True,
            panel=preset["panel"],
            judge=preset["judge"],
            max_tokens=mt,
        )
        return result, used_id or (preset["judge"])
    else:
        # Single-model stage: OVERRIDE the agent's hard Opus pin with the per-mode model
        # so Balanced/Economic are genuinely cheap. Quality keeps Opus.
        single_model = {
            "high": "or-opus",
            "mixed": "or-sonnet46",
            "economic": "or-llama33",
        }[eff_mode]
        try:
            result, used_id = route(
                llm,
                messages,
                model_id=single_model,
                goal=eff_mode,
                fusion=False,
                max_tokens=mt,
            )
            return result, used_id or single_model
        except Exception as exc:
            # A single transient provider/model failure shouldn't kill the whole run.
            # Retry once on a safe, always-available fallback model before giving up.
            from backend.router import recommend

            fb = recommend(eff_mode)
            if fb.id == single_model:
                raise RuntimeError(
                    f"Editorial stage '{stage}' failed on {single_model}: {exc}"
                )
            try:
                result, used_id = route(
                    llm,
                    messages,
                    model_id=fb.id,
                    goal=eff_mode,
                    fusion=False,
                    max_tokens=mt,
                )
                return result, used_id or fb.id
            except Exception as exc2:
                raise RuntimeError(
                    f"Editorial stage '{stage}' failed on {single_model} "
                    f"(and fallback {fb.id}): {exc} | {exc2}"
                )


def _brand_block(brand: BrandProfile) -> str:
    """Reusable brand-voice injection (the `_instructions_block` pattern)."""
    parts = [f"BRAND VOICE: {brand.voice_prompt.strip()}"]
    if brand.link_url:
        parts.append(
            "Brand link (cite NATURALLY and only where relevant, never as a hard sell, "
            f"at most once): {brand.link_url}"
        )
    if brand.forbidden_phrases:
        parts.append(
            f"FORBIDDEN phrases - never use any of these: {brand.forbidden_phrases}"
        )
    parts.append(
        "EDITORIAL METHOD (angle-first, never summarize): extract independent ideas and "
        "expand each into original content; do NOT simply shorten the essay. Build one clear "
        "insight per asset. Score/rank angles by authority, originality and commercial relevance, "
        "then create all platform variants for the strongest angle before moving to the next."
    )
    parts.append(
        "ANTI-AI TELL RULES: avoid perfect paragraph lengths, repeating sentence structures, "
        "predictable transitions, overuse of em dashes, rhetorical 'lists of three', obvious "
        "'firstly/secondly', artificial enthusiasm, corporate/marketing/LinkedIn cliches, and "
        "repeated vocabulary. Every version should feel written by a different human. Never "
        "sound generated."
    )
    return "\n".join(parts)


def _safe_json(text: str) -> Optional[dict]:
    """Parse a model's JSON reply, tolerating ```json fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # Last resort: grab the first {...} span.
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(t[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _estimate_credits(agent_id: str, text: str) -> int:
    """Mirror run_agent's credit estimate (base + ~1 per 4000 chars generated)."""
    agent_def = get_agent(agent_id)
    base = agent_def.base_credits if agent_def else 8
    return base + max(1, len(text) // 4000)


def run_editorial_pipeline(
    session: Session,
    user: User,
    essay: str,
    brand_id: int,
    platforms: list[str],
    llm: LLMClient,
    mode: Optional[str] = None,
    max_ideas: int = 8,
    run_multiplier: bool = False,
) -> dict:
    brand = session.get(BrandProfile, brand_id)
    if brand is None:
        brand = session.exec(select(BrandProfile).where(BrandProfile.is_default == True)).first()  # noqa: E712
    if brand is None:
        raise RuntimeError("No brand profile configured")
    brand_block = _brand_block(brand)

    # Always resolve the user within THIS session. A User loaded in another session
    # (e.g. the request session, passed into a worker thread) is detached here and
    # accessing .id triggers a cross-session lazy refresh that crashes SQLAlchemy's row
    # processor ("tuple index out of range"). Re-load by id so we own the instance.
    if user is not None:
        effective_user = session.get(User, user.id) or get_or_create_dev_user(session)
    else:
        effective_user = get_or_create_dev_user(session)

    run = EditorialRun(
        user_id=effective_user.id,
        brand_id=brand.id,
        essay_text=essay[:8000],
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    run_id = run.id
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS

    def _guard() -> None:
        """Raise to abort the run if it was canceled or exceeded a budget guardrail.
        Checked between stages and after every asset so a runaway chain stops promptly
        (killing the dev server does NOT stop in-flight OpenRouter billing)."""
        if is_canceled(run_id):
            raise EditorialCanceled(run_id)
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Run exceeded the {RUN_TIMEOUT_SECONDS // 60}-minute time limit and was "
                "auto-canceled to cap cost. The assets created so far are saved."
            )
        if total_credits > RUN_MAX_CREDITS:
            raise RuntimeError(
                f"Run exceeded the {RUN_MAX_CREDITS}-credit budget and was auto-canceled "
                "to cap cost. The assets created so far are saved."
            )

    norm_mode = mode if mode in ("economic", "mixed", "balanced", "high", "quality") else None
    total_credits = 0
    # Pre-initialized so the cancellation handler can read them whether or not any
    # stage completed. Assets saved before cancellation are preserved.
    ideas: list = []
    selected_ideas: list = []
    assets: list = []

    try:
        # ---- Stage 1: Idea Miner ----
        _guard()
        miner_in = f"SOURCE ESSAY:\n\"\"\"\n{essay}\n\"\"\"\n\n{brand_block}"
        ideas_text, m1 = _run_stage(llm, session, "idea_miner", miner_in, norm_mode, run_id=run_id)
        ideas_data = _safe_json(ideas_text) or {"ideas": []}
        ideas = ideas_data.get("ideas", [])
        if not ideas:
            # The miner returned no parseable ideas (truncated/garbage model reply).
            # Fail fast BEFORE the later stages so we don't charge for an empty run.
            run.status = "failed"
            session.add(run)
            session.commit()
            raise RuntimeError(
                "Idea Miner returned no usable ideas (model reply was empty or not valid JSON). "
                "No credits were charged for downstream stages."
            )
        bank = IdeaBank(run_id=run.id, ideas_json=json.dumps(ideas, ensure_ascii=False))
        session.add(bank)
        # Publish live progress so the polling UI shows mined-count instead of 0.
        run.ideas_count = len(ideas)
        session.add(run)
        session.commit()
        total_credits += _estimate_credits("editorial-idea-miner", ideas_text)

        # ---- Stage 2: Strategist ----
        _guard()
        strat_in = (
            f"IDEA BANK (JSON):\n{json.dumps(ideas, ensure_ascii=False)}\n\n"
            f"Pick the {max_ideas} best, most diverse ideas for a 4-week calendar.\n"
            f"{brand_block}"
        )
        plan_text, m2 = _run_stage(llm, session, "strategist", strat_in, norm_mode, run_id=run_id)
        plan = _safe_json(plan_text) or {"selected": [], "calendar": []}
        selected = plan.get("selected", [])
        # Fall back to the top ideas by (novelty+reach) if the strategist returned none.
        if not selected and ideas:
            selected = [
                i.get("id")
                for i in sorted(
                    ideas,
                    key=lambda x: (x.get("novelty", 5) + x.get("reach", 5)),
                    reverse=True,
                )[:max_ideas]
            ]
        # HARD CAP: the strategist may return more ideas than the user asked for (or
        # ignore max_ideas entirely). Without this, a "max 4" request could process 12+
        # ideas => dozens of extra model calls (Creator/Humanizer/Quality per asset) and
        # a 10x token blow-up. The user's max_ideas is a hard ceiling, never exceeded.
        if max_ideas and len(selected) > max_ideas:
            selected = selected[:max_ideas]
        cal = EditorialCalendar(run_id=run.id, calendar_json=json.dumps(plan, ensure_ascii=False))
        session.add(cal)
        session.commit()
        total_credits += _estimate_credits("editorial-strategist", plan_text)

        # Map id -> idea for quick lookup.
        idea_by_id = {i.get("id"): i for i in ideas}
        selected_ideas = [idea_by_id[s] for s in selected if s in idea_by_id]

        # ---- Stages 3-5: Creator -> Humanizer -> Quality Director (per idea) ----
        platforms_arg = platforms or EDITORIAL_PLATFORMS
        # Hard ceiling on total assets so a misbehaving model (returning a huge platform
        # list or thousands of one-liners) cannot spawn an unbounded number of paid calls.
        # Roughly: selected_ideas * platforms (each platform = 1 post asset) + one-liner
        # kinds. Capped well above any sane request to still allow quotes/hooks (10/20).
        MAX_ASSETS = max(40, (len(selected_ideas) * len(platforms_arg)) + 80)
        assets: list[dict] = []
        for idea in selected_ideas:
            if len(assets) >= MAX_ASSETS:
                break
            _guard()
            idea_block = (
                "IDEA to create for (create ONLY for THIS idea, never reference the essay):\n"
                f"title: {idea.get('title', '')}\n"
                f"summary: {idea.get('summary', '')}\n"
                f"angle: {idea.get('angle', '')}\n\n"
                "Platforms to produce (EXACTLY 4 versions each): "
                f"{', '.join(platforms_arg)}.\n"
                f"For quotes/hooks/questions/predictions produce these counts: "
                f"{_KIND_COUNTS}.\n\n{brand_block}"
            )
            creator_text, mc = _run_stage(llm, session, "creator", idea_block, norm_mode, run_id=run_id)
            total_credits += _estimate_credits("editorial-creator", creator_text)
            created = _safe_json(creator_text) or {"assets": []}

            for asset in created.get("assets", []):
                if len(assets) >= MAX_ASSETS:
                    break
                platform = asset.get("platform", "")
                kind = asset.get("kind", "post")
                versions = asset.get("versions", [])

                # The Creator can return several assets in ONE call, so the Humanizer /
                # Quality Director echo ALL of them back. Match the reply to THIS asset by
                # platform+kind (fall back to the first returned asset if no match).
                def _match_asset(resp_assets):
                    for a in resp_assets:
                        if a.get("platform") == platform and a.get("kind") == kind:
                            return a
                    return (resp_assets or [{}])[0]

                # Stage 4: Humanizer (per asset).
                hum_in = (
                    "Asset to humanize:\n"
                    f"{json.dumps({'platform': platform, 'kind': kind, 'versions': versions}, ensure_ascii=False)}\n\n"
                    f"{brand_block}"
                )
                hum_text, mh = _run_stage(llm, session, "humanizer", hum_in, norm_mode, run_id=run_id)
                total_credits += _estimate_credits("editorial-humanizer", hum_text)
                hum = _safe_json(hum_text) or {}
                hum_first = _match_asset(hum.get("assets", [{}]))
                hum_versions = hum_first.get("humanized_versions", versions) or versions

                # Stage 5: Quality Director (per asset).
                qd_in = (
                    "Asset to score/rewrite:\n"
                    f"{json.dumps({'platform': platform, 'kind': kind, 'versions': hum_versions}, ensure_ascii=False)}\n\n"
                    f"{brand_block}"
                )
                qd_text, mq = _run_stage(llm, session, "quality_director", qd_in, norm_mode, run_id=run_id)
                total_credits += _estimate_credits("editorial-quality-director", qd_text)
                qd = _safe_json(qd_text) or {}
                qd_first = _match_asset(qd.get("assets", [{}]))
                final_versions = qd_first.get("final_versions", hum_versions) or hum_versions
                score = int(qd_first.get("quality_score", 0) or 0)

                # One-liner kinds (quotes/hooks/questions/predictions) keep their full
                # requested counts; post/thread/carousel kinds are capped at 4 versions.
                keep = _KIND_COUNTS.get(kind, 4) if kind in _KIND_COUNTS else 4
                stored_versions = final_versions[:keep]

                row = EditorialAsset(
                    run_id=run.id,
                    idea_ref=idea.get("title", ""),
                    platform=platform,
                    kind=kind,
                    content=json.dumps(stored_versions, ensure_ascii=False),
                    quality_score=max(0, min(10, score)),
                )
                session.add(row)
                # Publish live progress after every asset so the UI counts up in real time.
                run.assets_count = len(assets) + 1
                session.add(run)
                session.commit()
                session.refresh(row)
                assets.append({
                    "id": row.id,
                    "platform": platform,
                    "kind": kind,
                    "idea_ref": row.idea_ref,
                    "versions": stored_versions,
                    "quality_score": row.quality_score,
                })
                _guard()

        # ---- Stage 6 (optional): Multiplier ----
        multiplier_ip = []
        if run_multiplier and assets:
            _guard()
            mult_in = (
                "Created assets (platform/kind only) for context:\n"
                f"{json.dumps([{'platform': a['platform'], 'kind': a['kind']} for a in assets], ensure_ascii=False)}\n\n"
                f"{brand_block}"
            )
            mult_text, mm = _run_stage(llm, session, "multiplier", mult_in, norm_mode, run_id=run_id)
            total_credits += _estimate_credits("editorial-multiplier", mult_text)
            mult = _safe_json(mult_text) or {}
            multiplier_ip = mult.get("ip", [])

        run.status = "done"
        run.ideas_count = len(ideas)
        run.assets_count = len(assets)
        run.credits_used = total_credits
        session.add(run)
        session.commit()

        charge(session, effective_user, "editorial-pipeline", total_credits, 0, 0)

        return {
            "run_id": run.id,
            "brand": {"id": brand.id, "name": brand.name, "link_url": brand.link_url},
            "ideas_count": len(ideas),
            "selected_ideas": len(selected_ideas),
            "assets": assets,
            "multiplier_ip": multiplier_ip,
            "credits_used": total_credits,
            "remaining_credits": effective_user.credits if effective_user else 0,
        }
    except EditorialCanceled:
        # User (or guardrail) aborted: mark canceled, keep whatever assets we saved.
        # We do NOT re-raise — the route treats this as a terminal, expected state.
        run.status = "canceled"
        run.canceled = True
        run.error = "Run was canceled."
        run.ideas_count = len(ideas)
        run.assets_count = len(assets)
        run.credits_used = total_credits
        session.add(run)
        session.commit()
        return {
            "run_id": run.id,
            "brand": {"id": brand.id, "name": brand.name, "link_url": brand.link_url},
            "ideas_count": len(ideas),
            "selected_ideas": len(selected_ideas),
            "assets": assets,
            "multiplier_ip": [],
            "credits_used": total_credits,
            "remaining_credits": effective_user.credits if effective_user else 0,
        }
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        session.add(run)
        session.commit()
        if isinstance(exc, InsufficientCredits):
            raise
        raise
