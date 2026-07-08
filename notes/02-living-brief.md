# The Living Project Brief — Gadgents Agent Agency

> **Purpose:** This brief is the single source of truth for what this codebase is building, what is done, what remains, and how to operate and extend it. It is written so any LLM can continue development without losing context.

---

## 1) What we are building
A modular **Agent Agency** backend that hosts a growing army of specialized AI agents and “offices” (multi‑agent divisions). The system supports:
- Agent routing and execution
- Skill/knowledge libraries (markdown‑based)
- Tool registry with safe allowlists per agent
- Extensible “offices” for client work (marketing, distribution, automation, company founding, etc.)
- Local or hosted deployment

**Primary goal:** Use this system to deliver paid client solutions quickly by assembling the right agent(s), knowledge, and tools for each project.

---

## 2) What is built so far (functional)
### ✅ Core system
- Agent registry + routing (`src/agents/index.ts`)
- Agent contexts via Pi‑mono (`src/core/piAgentFactory.ts`)
- Tool registry with allowlists (`src/core/toolRegistry.ts`)
- Skill library + MOC graph (`skills/`)

### ✅ Fixed and improved agents
- **browser-agent** is now a real `AgentDefinition` with `handle()` (not a stub)
- **gpu-renter** logic upgraded to parse requirements and require approval before renting

### ✅ New agent divisions (fully functional)
- **Company Founding Office** (`company-founding`)
- **Distribution Engineer** (`distribution-engineer`)
- **App Growth UGC Engine** (`app-growth-ugc`)
- **AI Character Studio** (`ai-character-studio`)
- **Newsletter Operator** (`newsletter-operator`)
- **Automation Builder** (`automation-builder`)
- **Local Lead Gen** (`local-lead-gen`)

Each includes:
- AgentDefinition in `src/agents/`
- Tool allowlist entries
- Skill‑library path hints
- Domain knowledge docs + MOCs

### ✅ Functional tools (baseline)
- web_search / fetch_content stubs
- agent_browser tool
- placeholder tools for marketing sub‑agents (now registered)
- local lead tools: `maps_lead_search`, `lead_email_extract`, `lead_dedupe`, `lead_clean`, `lead_export_csv`, `lead_export_summary`
- Postiz publish stub: `postiz_publish`
- Analytics store in SQLite: `analytics_log`, `analytics_report`

---

## 3) Functional agents (ready now)
**Core agents:** coding, marketing, translation, news, trading, daily‑life, teacher, media‑analysis, storyteller, wealth‑strategist, office, legal‑insurance, social‑media, gaming, seo, news‑channel, artist, project‑manager, codebase‑course, browser‑agent

**New agents:** company‑founding, distribution‑engineer, app‑growth‑ugc, ai‑character‑studio, newsletter‑operator, automation‑builder, local‑lead‑gen

---

## 4) What still needs to be built
### High priority
1. **Real tool integrations** to replace placeholders:
   - Postiz API
   - Social scheduling APIs
   - Analytics dashboards
   - Maps data provider
   - Social listening tools

2. **Marketing sub‑agents** (AgentScaffold) should eventually get:
   - richer prompts
   - real tools instead of placeholders
   - live integration pipelines

3. **Web search provider** (currently stubbed)

### Medium priority
4. Add richer long‑form knowledge docs for marketing, distribution, automation
5. Build real client “playbooks” and templates for common services

---

## 5) How to operate the system
### Local development
```bash
npm install
npm run dev
```
- API runs on default port 3000
- Agents are reachable at `/api/agents/:id/chat`

### Live agent testing
```bash
node --import tsx scripts/test-new-agents-live.ts
```

### Local lead pipeline CLI
```bash
node --import tsx scripts/lead-pipeline-cli.ts --keyword "dentist" --location "Austin, TX" --out leads.csv
```

### Hosting recommendation
**Best practice:** host this on a VPS or container platform (Coolify works well).
- Use `NODE_ENV=production`
- Add reverse proxy (TLS) + auth (`REQUIRE_AUTH=true`, `API_KEYS=...`)
- Persist state (recommended): Postgres + Redis

Production service integrations (recommended):
- **LiteLLM gateway:** set `OPENAI_BASE_URL` to LiteLLM and route models through it
- **SearXNG:** set `SEARXNG_BASE_URL` to enable real `web_search`
- **Redis:** set `REDIS_URL` to enable distributed rate limiting
- **Postgres (Prisma):** set `DATABASE_URL` and run `prisma migrate deploy`

---

## 6) How to use this codebase for paying clients
### Pattern
1. Identify the client goal → map to agent division
2. Load the relevant agent(s)
3. Use the skill graph to inject domain knowledge
4. Execute workflows and deliver outputs

### Examples
- **Startup founder:** use Company Founding Office
- **Local business lead gen:** use Local Lead Gen agent
- **App creator:** use App Growth UGC Engine
- **Creator monetization:** use Newsletter Operator
- **Automation consulting:** use Automation Builder

### Extraction / reuse
- Each agent is a reusable product
- Use prompts + knowledge docs as “client playbooks”
- Clone these agents into project‑specific forks if needed

---

## 7) Knowledge/skills optimization recommendations
1. **Add long‑form docs** for marketing, distribution, and automation
2. **Add structured templates** (JSON/YAML) for:
   - onboarding plans
   - campaign plans
   - lead pipeline configs
3. **Consolidate overlapping docs** to reduce duplication
4. **Add more MOCs** for easy navigation

---

## 8) Performance optimization recommendations
1. Add real web search (SerpAPI, Tavily, or self‑hosted crawler)
2. Replace placeholder tools with real APIs
3. Add caching for frequent prompts
4. Add concurrency controls + rate limits
5. Add durable analytics storage (Postgres)

---

## 9) Required API keys (current optional list)
- **Postiz:** `POSTIZ_API_URL`, `POSTIZ_API_KEY`
- **Maps provider:** `RAPIDAPI_KEY` + provider URL/host (if used)
- **Search provider:** optional (not wired yet)

---

## 10) Minimal roadmap (next 30–60 days)
- Replace placeholders with real integrations
- Build client‑ready playbooks for top 5 agent divisions
- Add real web search
- Add automated reporting / dashboards
- Publish first client case studies using this system

---

## 11) Owner’s note
This file is the persistent ground truth. Update it after every major change so the system remains stable for new contributors and LLMs.
