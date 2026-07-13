# Gadgents v2

Lean **bot-rental** product: paywalled AI agents, accessible to the public through a web
frontend. Built from scratch (the previous `gadgents-archive/` folder holds the old, over-scoped
prototype).

## What it does
- Users register, get free starter credits, and rent bots by chatting with them.
- Usage is metered in credits (100 credits = $1). Out of credits → paywall.
- Hero flow — **Content Studio**: paste an article / image notes / video idea + pick platforms → a
  `prompt-engineer` agent turns it into per-platform prompts → a `content-producer` agent turns those
  into finished, platform-ready posts (captions, hooks, hashtags).
- Billing has a working mock (buy credits / subscribe) and a Stripe webhook hook ready for live mode.

## Stack
- **Backend**: FastAPI + SQLModel (SQLite dev / Postgres prod), JWT auth, homegrown LLM client with
  health-aware provider **fallback** (`openai → groq → openrouter → ollama`). No external agent
  framework.
- **Frontend**: React + Vite, proxies `/api` to the backend.

## Run locally

**One command (recommended):**
```bash
./dev.sh          # starts backend (:8000) + frontend (:5173); Ctrl+C stops both
```
Open http://localhost:5173. The dev `.env` has login + paywall disabled, so you can test
every agent with no account and no credits.

**Or run them separately:**
```bash
# backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env            # add at least one LLM provider key
uvicorn backend.app:app --port 8000 --reload

# frontend (separate terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

**Firecrawl (optional):** the Lead Finder can do JS-rendered discovery + deep domain audit
when its "Use Firecrawl" box is ticked. For that, run firecrawl-simple (or firecrawl) in
Docker so it answers at `http://localhost:3002` (`FIRECRAWL_BASE_URL` in `.env`). Without it,
Lead Finder falls back to DuckDuckGo + HTTP mode. `dev.sh` prints whether Firecrawl is reachable.

## Where things live
```
backend/
  app.py            FastAPI app + router wiring
  config.py         env-driven settings
  db.py             SQLModel models (User, Usage, Subscription)
  auth.py           JWT + password hashing
  llm.py            LLMClient: provider registry + fallback
  agents.py         agent primitive + registry
  pipeline.py       content pipeline (prompt-engineer -> content-producer)
  billing.py        credit charge / grant
  routes/           auth, agents, billing, pipeline
frontend/           React app (login, bot catalog, chat, Content Studio, billing)
notes/              demoted idea docs from the old project (reference only, not loaded at runtime)
gadgents-archive/   the previous, superseded monorepo
.factory/           local factory config (gitignored, per your provision)
```

## Notes
- `notes/` is the old 785-file "skill library" reduced to the 6 useful idea docs. They are reference
  material only — the running system does not load them.
- Stripe is stubbed: set `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` and finish
  `backend/routes/billing.py:stripe_webhook` to go live.
