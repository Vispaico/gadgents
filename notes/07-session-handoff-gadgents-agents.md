# Gadgents — Agent Build Session Handoff #2 (recap + next steps)

> Read this FIRST in the next chat. All code on disk is the source of truth; this recap
> is just so we continue seamlessly. The previous handoff (notes/06-...) covered the first
> agent-build session; this one continues from there and is the current state. We started a
> fresh chat the same way (read the handoff, then the todo list reflects real state).

## How to resume a chat from this note
1. Open this file (notes/07-...) and skim it.
2. Run `git status --porcelain` + `git log --oneline -5` to see what changed since.
3. The agent registry is the source of truth: `python3 -c "from backend.agents import list_production_agents; [print(a.id, a.fusion, a.mode, a.router_model) for a in list_production_agents()]"` (with venv active).
4. The frontend is where the user tests/tunes next. `./dev.sh` boots both servers.

## Stack (unchanged from README)
- Backend: FastAPI + SQLModel (SQLite dev / Postgres prod), homegrown `LLMClient` with
  health-aware provider fallback. No external agent framework.
- Frontend: React + Vite (proxies `/api` to :8000), port 5173.
- Dev bypass is ON in `.env`: `REQUIRE_LOGIN=false`, `ENABLE_PAYWALL=false` (test every
  agent with no login / no credits). Set both `true` before going live.
- Secrets in `.env` (gitignored). `.env.example` documents all keys incl. Firecrawl.

## Run locally (one command)
```bash
cd /Users/n3ils/Sites/gadgents
./dev.sh            # backend :8000 + frontend :5173; Ctrl+C stops both
```
Open http://localhost:5173. Firecrawl note: if firecrawl-simple docker is up on :3002,
Lead Finder's "Use Firecrawl" box enables JS-rendered discovery + deep audit; otherwise it
falls back to DuckDuckGo + HTTP. `dev.sh` prints whether :3002 is reachable.

## Provider + model architecture (unchanged since #1)
Providers (`backend/config.py` `llm_provider_order`): `openrouter,openai,ollama`.
- OpenRouter base URL fixed to `https://openrouter.ai/api/v1`.
- OpenAI + OpenRouter model ids are BOTH env-overridable (`OPENAI_MODEL_*`,
  `OPENROUTER_MODEL_*`) in `.env`. Add a new model to the catalog in `backend/router.py`
  (`MODEL_CATALOG`) and optionally add a matching env key in `config.py`.
- Fusion router `backend/router.py`: `route(..., fusion=, panel=, judge=)`. Catalog ids
  like `or-opus`, `oa-sol`. Presets per mode in `_FUSION_PRESETS`.

## Agents built — CURRENT STATE (7 production-ready)
All registered in `backend/agents.py`; `list_production_agents()` returns only
`production_ready=True`. Auto-wired (no router edit needed to add an agent).

1. `prompt-engineer` (`or-qwen37`, mixed) — article/image/video idea → per-platform prompts.
2. `content-producer` (`or-llama33`, mixed) — prompt/brief → finished platform content.
   (1+2 chain internally = Content Studio hero flow, `backend/pipeline.py`,
   route `/api/pipeline/content`.)
3. `coder` (`oa-codex`, mixed) — coding Q&A/snippets.
4. `personal-planner` (`mode=high`, no pin) — structured day plan (JSON: tasks/time_blocks/
   reminders) + learning layer (`PlannerMemory`). Endpoints `/plan /inbox /tasks /reminders
   /memory` in `backend/routes/planner.py`. DB models in `backend/db.py`. Proactive reminder
   LOOP + delivery channel = STILL DEFERRED (schema ready, not wired).
5. `content-repurposer` (Fusion: panel `[or-ds-pro, oa-sol, or-opus, or-llama33]`, judge
   `or-opus`, mode high) — long content → multi-platform posts + media suggestions + short
   video script package. Route `/api/repurposer/run`, `/briefs`. DB: `ContentBrief`,
   `ContentOutput`. NOTE: repurposer groups output BY PLATFORM (not a fixed 6×4 matrix) on
   purpose — free-form instructions drive number of posts/channels (user decision: keep
   general, do NOT hardcode a matrix).
6. `lead-finder` (`or-sonnet46`, mixed, production_ready=True) — ICP-driven public-web lead
   discovery + fit scoring + outreach angle. NOT a single model: an orchestrator chain in
   `backend/leads/` that reuses the user's Scraper toolkit discovery/analysis
   (`websearch_utils` style: Firecrawl or DuckDuckGo + HTTP, email/site-age extraction) and
   routes each stage through the Fusion router. GDPR-safe: public web + business emails only;
   Cognism noted as manual follow-up. Frontend = ICP wizard (structured fields + chat panel)
   in `LeadFinder` tab. DB: `LeadQuery`, `Lead`. Route `/api/leadfinder/icp-chat`, `/run`,
   `/leads`.
7. `wan-video` (Fusion: panel `[or-opus, or-ds-pro, oa-sol, or-sonnet46]`, judge `or-opus`,
   mode high) — source image + concept → Wan2.2 image-to-video storyboard. Each shot = ONE
   ~5s clip with ONE camera move from a 50-move vocabulary (`backend/wan/camera_moves.json`).
   Built around a ONE-SHOT contract so stitched 5s clips form a coherent video. Format-
   structure knowledge (ads/docs/short films pacing, scene lengths) is a TUNING hook
   (`FORMAT_PRESETS` in `backend/wan/prompt_builder.py`, currently empty; `format_kind` param
   + UI dropdown already plumbed). DB: `WanVideoBrief`, `WanVideoShot`. Route `/api/wan/run`,
   `/briefs`. Frontend = `WanVideo` tab.

## Frontend tabs (Home nav)
Bots · Content Studio · Lead Finder · Wan Video · Billing. Dev-bypass skips login:
`/api/config` returns `require_login` so the UI goes straight to Home with a synthetic user
(this was a bug fix — see below).

## Bugs / fixes done this session
- Frontend showed login screen even with `REQUIRE_LOGIN=false` (401 on /api/auth/login when
  typing creds). FIX: added `GET /api/config` returning `require_login`/`enable_paywall`;
  frontend fetches it on load and skips auth view in bypass mode (synthetic dev user).

## Verified this session
- App boots 200; `/api/config` returns flags; `/health` ok.
- All 7 agents register & appear in production list; `wan-video` embeds the 50-move vocabulary
  in its system prompt.
- End-to-end chains tested with MOCKED LLM (no live network in sandbox): lead-finder
  ICP→discovery→audit→scoring→persist; wan-video storyboard parse→persist.
- `dev.sh` boots both servers (backend health 200, frontend 200); Firecrawl reachability
  notice works.

## Decisions locked
- Lead Finder reuses Scraper toolkit + our Fusion router as an orchestrator chain, NOT a
  single Fusion call. Vendored into `backend/leads/` (self-contained; deps `requests`,
  `beautifulsoup4` added to pyproject).
- Lead Finder = public-web/GDPR-safe; Cognism is a manual later step (documented, not built).
- Repurposer output stays platform-grouped and free-form (no fixed matrix) per user choice.
- Wan agent: one-shot 5s-per-shot contract; format-structure knowledge is a tuning-phase hook.
- Freelance job finder & applier = still ON HOLD (user put it on ice).
- CloakBrowser / PageIndex = NOT used (CloakBrowser = overkill/ToS risk; PageIndex = RAG
  retrieval, not discovery). Firecrawl-simple = kept (already in Scraper toolkit).

## Next steps (per original plan + where we are)
- PER-AGENT TUNING (next, in progress): adjust `router_model` pins / `mode` / Fusion usage
  per agent once the user has used the frontend and seen real outputs. Candidate tweaks:
  * lead-finder ICP stage already Fusion; audit uses `or-sonnet46` (cheap), scoring
    `or-llama33`. Possibly raise scoring to a stronger model.
  * wan-video Fusion panel is heavy (4 models incl or-opus x2); consider economic preset for
    drafts.
  * personal-planner mode=high already.
- PRODUCTIONIZE (deferred): hosting; flip `REQUIRE_LOGIN=true` + `ENABLE_PAYWALL=true`; wire
  planner proactive reminder LOOP + delivery channel; repurposer URL-ingestion (it currently
  takes pasted text, not URLs); monthly token-budget cap.
- WAN FORMAT PRESETS: populate `FORMAT_PRESETS` with ads/docs/short-film/podcast structure
  knowledge when the user supplies it; flows into prompt automatically (no route change).

## What the next chat needs from the user
- Feedback from frontend testing (which agents feel weak / expensive / wrong) to drive tuning.
- The format-structure knowledge material for Wan presets (ads, docs, reels, scene lengths).
- Confirmation before flipping any live flags.

## Context window note
When this chat's context approaches ~70%, START A NEW CHAT, re-read notes/07 (this file) first,
then run `git status`/`git log` and the agent-registry one-liner above. The handoff doc is the
single source of continuity; keep it updated at each session boundary.
