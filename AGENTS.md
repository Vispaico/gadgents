# Gadgents v2

## Run
- `./dev.sh` — starts backend (:8000) + frontend (:5173); Ctrl+C stops both.
  - **Do NOT add `--reload` to uvicorn.** The editorial pipeline runs as a background
    thread; `--reload` kills in-flight runs on any file change, leaving orphaned state.
  - Requires `.venv/` and `frontend/node_modules/` pre-installed.
- Set `REQUIRE_LOGIN=false, ENABLE_PAYWALL=false` in `.env` to test every agent without
  an account or credits. `.env.example` shows current defaults as true.

## Architecture
- **Backend**: FastAPI + SQLModel, entrypoint `backend.app:app`. No external agent
  framework — custom LLM client with per-model health-aware fallback.
- **Frontend**: React + Vite, proxies `/api` to `localhost:8000`.
- **Models**: defined in `backend/db.py`. SQLite in dev (`gadgents.db`), Postgres in prod.
  Schema migration is handled at startup (`init_db` + `_ensure_columns` — only ADD columns).
- **Agent registry**: `backend/agents.py` — agents self-register via `agent()` factory.
  Set `production_ready=True` to expose via API; `show_in_bots=False` hides from the Bots
  page but still usable in flows (Content Studio etc.).
- **Model routing** (`backend/router.py`): three cost modes (high / mixed / economic) and
  an optional Fusion mode (panel + judge multi-model). Agent can pin a `router_model`
  (catalog id), use a Fusion panel+judge, or fall back to mode-based selection.
- **LLM provider order**: openrouter, nvidia, openai, deepseek, ollama (env-configurable).
  Health is tracked per (provider, model), not per provider — one throttled model doesn't
  cool down other models on the same gateway.

## Key quirks
- LLM POST runs out-of-process via `subprocess -m backend._llm_post_child` because httpx
  timeouts and signals fail to interrupt a stalled recv on macOS. Do NOT refactor to
  in-process httpx calls for the main completion path.
- `brain/` is an openkb wiki (`brain/.openkb/config.yaml`). Not application code.
  `brain/wiki/AGENTS.md` documents the wiki schema, NOT this repo.
- `notes/` and `gadgents-archive/` are legacy/reference only — not loaded at runtime.
- Lead Finder agent has a Firecrawl backend: start `firecrawl-simple` in Docker on
  `localhost:3002` for JS-rendered discovery; otherwise falls back to DuckDuckGo + HTTP.
- Social Listener agent requires `pip install cloakbrowser[geoip]` and a persistent
  browser profile dir (`SOCIAL_PROFILE_DIR`).
- Stripe is stubbed: set `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` and finish
  `backend/routes/billing.py:stripe_webhook` to go live.

## No tests, no lint, no CI
This repo has no test infrastructure, no lint/formatter config, no typecheck setup, and
no CI workflows. Commands like `pytest`, `ruff`, `mypy` are not configured.
