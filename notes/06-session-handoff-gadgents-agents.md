# Gadgents — Agent Build Session Handoff (recap + next steps)

> SUPERSEDED by notes/07-session-handoff-gadgents-agents.md (current state). Read 07 first.

> Read this first in the next chat. All code on disk is the source of truth; this recap
> is just so we continue seamlessly. Context was getting deep, so we started a fresh chat.

## Stack (unchanged from README)
- Backend: FastAPI + SQLModel (SQLite dev / Postgres prod), homegrown `LLMClient` with
  health-aware provider fallback. No external agent framework.
- Frontend: React + Vite (proxies `/api`), port 5173.
- Run backend: `uvicorn backend.app:app --port 8000 --reload`
- Dev bypass is ON in `.env`: `REQUIRE_LOGIN=false`, `ENABLE_PAYWALL=false` (lets you test
  every agent with no login / no credits). Set both `true` before going live.
- Secrets in `.env` (gitignored). `.env.example` documents all keys.

## Provider + model architecture (IMPORTANT — changed a lot this session)
Providers (= `backend/config.py` `llm_provider_order`): `openrouter,openai,ollama`
- OpenCode was REMOVED (user dropped it).
- OpenRouter base URL fixed to `https://openrouter.ai/api/v1`.
- OpenAI model ids and OpenRouter model ids are BOTH env-overridable via `.env`
  (`OPENAI_MODEL_*`, `OPENROUTER_MODEL_*`) — see `config.py` + `.env`.

### Fusion-like router — `backend/router.py`
- Catalog of 25 models (`MODEL_CATALOG`), each a `ModelEntry(provider, model, tier, modes)`.
- 3 modes: `high` (High Quality), `mixed` (default, not expensive but high quality),
  `economic` (Very Economic).
- `recommend(goal)` picks default per mode (tier-preferred).
- `route(...)` selects one model, OR (with `fusion=True`) runs a PANEL of models in parallel
  + a JUDGE that synthesizes — modeled on OpenRouter Fusion but on OUR models.
- `complete_targeted(provider, model, ...)` in `backend/llm.py` runs one exact provider+model.
- Endpoints (`backend/routes/router.py`): `/api/router/models`, `/api/router/recommend`,
  `/api/router/fusion-presets`, `/api/router/chat` (supports `goal`, `model_id`, `fusion`,
  `panel`, `judge`).

### Agent primitive — `backend/agents.py`
- Agents self-register via the `agent(...)` factory into `REGISTRY`; exposed via
  `list_production_agents()` (only `production_ready=True`). Adding an agent needs NO router
  edit (auto-wired). They appear in `/api/agents` automatically.
- `AgentDef` fields: `id, name, description, system_prompt, model, input_tool, base_credits,
  router_model (catalog id pin, None=use mode), mode (high|mixed|economic),
  fusion (bool), fusion_panel (list of catalog ids), fusion_judge (catalog id),
  production_ready`.
- `run_agent(agent, user_input, llm, memory=None)` routes through `route(...)` honoring
  `router_model`/`mode`/`fusion`/`fusion_panel`/`fusion_judge`. Returns (text, 0, 0, credits).
- Chat route `backend/routes/agents.py`: `POST /api/agents/{agent_id}/chat` (flat body
  `{"message": "..."}`), obeys `REQUIRE_LOGIN`/`ENABLE_PAYWALL`. Billing `charge()` is a
  no-op when paywall off.

## Agents built so far (5 total, all production_ready)
1. `prompt-engineer` — article/idea → per-platform prompts. pin: `or-qwen37`.
2. `content-producer` — brief/prompt → platform-ready posts. pin: `or-llama33`
   (user's "summaries/short posts" model).
3. `coder` — coding Q&A/snippets. pin: `oa-codex` (`gpt-5.1-codex`).
   (1+2 chain in `backend/pipeline.py` = hero Content Studio.)
4. `personal-planner` — personal secretary & planner (agent #1). `mode="high"`, JSON output
   (tasks/time_blocks/reminders with escalation/learned prefs). Learning layer via
   `PlannerMemory`. Endpoints in `backend/routes/planner.py`: `/plan`, `/inbox`, `/tasks`,
   `/reminders`, `/memory`. DB models in `backend/db.py` (InboxItem, Project, Task,
   CalendarEvent, TimeBlock, Reminder, KnowledgeItem, DailyReview, PlannerMemory).
   Proactive reminder LOOP + delivery channel = DEFERRED to productionize (schema ready).
5. `content-repurposer` — summarizer/vibe-preserving repurposer (agent #2). `fusion=True`,
   panel `[or-ds-pro, oa-sol, or-opus, or-llama33]`, judge `or-opus`. Outputs brief +
   per-channel posts (LinkedIn/FB/X/IG/YT/Shorts-TikTok) + media_suggestions + scene-annotated
   script package. Endpoints `backend/routes/repurposer.py`: `/run`, `/briefs`.
   DB: `ContentBrief`, `ContentOutput` in `backend/db.py`. Chain-ready into 1+2 (not auto).

## Decisions locked this session
- OpenCode removed; providers = openrouter, openai, ollama.
- OpenAI model ids env-overridable (user will paste exact names from OpenAI model page;
  `gpt-5.1-codex-mini` was 404 and dropped).
- Multi-model via Fusion (panel+judge), NOT a separate Next.js/Coolify stack.
- Agent #2 = single Fusion agent, not a chain and not standalone services.
- Freelance job finder & applier = ON HOLD (user put it on ice).
- Tuning of system prompts/rules/limits for existing agents = deferred (user chose build-all-
  first).
- Monthly token-budget cap = deferred until pay features go live.

## Next steps
- Build agent #3: LEAD FINDER (user-defined; user said they have an EXAMPLE to provide).
- Build agent #4: WAN2.2 IMAGE-TO-VIDEO PROMPT agent (user has a file with ~50 camera moves
  + other skill-set material to supply). This one also connects to agents 1+2 loosely.
- Then: tune model/router usage per agent; then PRODUCTIONIZE (hosting) for real-world testing
  (incl. the deferred planner reminder loop + delivery channel, and any URL-ingestion for
  repurposer).

## What the next chat needs from the user
- For lead finder: the user's example definition of "a lead" + where to look.
- For Wan2.2: the 50-camera-moves file + any other prompting/skill material.
- Confirm: per-agent `router_model` pins are user-adjustable via `.env` (OpenAI/OpenRouter ids);
  consider also making `router_model` per-agent pins env-overridable if desired.

## Verification notes
- Sandbox has NO network egress, so live LLM calls 404/ConnectionError here; all code paths
  verified via import + mocked `complete_targeted`. On the user's machine (real keys in `.env`)
  the calls work. `gpt-5.1-codex-mini` is NOT a valid model id (404) — do not re-add it.
- All endpoints return 200 on boot; JSON-orchestration for Fusion verified (4 panel + 1 judge
  = 5 completions, valid structured JSON with script scenes).
