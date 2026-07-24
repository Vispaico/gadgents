# Gadgents — Product & Architecture Ideas

> Captured from a planning chat (2026-07-19). Pure design notes: no code yet. The
> `notes/07-*` handoff is the source of continuity for implementation; this file is the
> forward-looking idea dump. Models referenced are the catalog ids resolvable from `.env`.

---

## 1. Multiple routers with different model sets, called per job

Yes. `backend/router.py` already supports purpose-tuned panels: `_FUSION_PRESETS` plus
per-agent `fusion_panel` / `fusion_judge`, and `route(..., fusion=, panel=, judge=)` lets any
agent/tool pick a specific panel at call time. The mode override (`override_mode` →
`_FUSION_PRESETS[mode]`) already swaps presets per call.

To formalize "several routers": define **named preset sets** in `router.py` — e.g.
`cheap`, `standard`, `premium`, `vision`, `legal`, `coding` — and expose a
`get_panel(name)` helper. Each agent/task calls `route(..., panel=get_panel("vision"))`.
The scaffolding is partly there; it mostly needs named presets + a resolver, not a rewrite.

---

## 2. Free/paid alternates per model + cross-provider failover

Yes. DeepSeek-v4-Flash alone appears as `or-ds-flash-free`, `or-ds-flash`,
`nv-ds4flfree` (poolside), `nv-ds4pprofree` (deepseek-ai), `ds4flash` — same model,
several providers/price tiers. The raw material already exists in `MODEL_CATALOG`.

Build a **model ladder** per role, e.g. `[or-ds-flash-free, nv-ds4flfree, ds4flash,
or-ds-flash]`, and a retry loop that walks the ladder on `429` / `5xx` / timeout, clearing
the per-(provider, model) cooldown the router already tracks (from the 2026-07-16
per-model-health fix). Single-model stages already rotate across catalog models (editorial
did this); generalize that `recommend(eff_mode)` into a ladder resolver so a call can fall
back free → paid → alternate provider automatically. Gap today: `route()` does panel
rotation but not a cross-provider free→paid ladder for single-model calls. Addition, not
rewrite.

---

## 3. Personal Secretary / Planner chat: text + image + video + file + audio

Use a **multimodal router**. Multimodal models in `.env`:
- `nv-omni` / `or-omni` = `nvidia/nemotron-3-nano-omni-30b` — text + image + video + audio
  (true omni input in one inference loop).
- `or-mimo25` / `or-mimo25pro` = `xiaomi/mimo-v2.5(-pro)` — image + video + text.
- `or-ge4` / `or-ge4free` = `google/gemma-4-31b-it` — image + video + text.
- `or-inkl` / `nv-inkl` = `thinkingmachines/inkling` — text + image + audio.
- `or-perc-mk1` = `perceptron/perceptron-mk1` — video understanding (QA, summarization,
  event detection, OCR, open-vocabulary detection).

Build a chat agent whose system prompt treats attachments as message content parts:
- images → base64 / data-url into the vision message.
- video → frame extraction OR pass straight to a video-native model (`nv-omni`,
  `or-mimo25pro`, `or-perc-mk1`); audio → transcript via `nv-omni` / `or-inkl` or a speech
  model, then attach the transcript.
- files (pdf/docx/xlsx) → extract text first via a `markitdown`-style path (OpenKB already
  bundles markitdown) or the existing `url_reader` logic, then attach as text.

Define a `multimodal_panel` = `[nv-omni, or-mimo25pro, or-ge4]` and a pre-processor that
normalizes each attachment type into a form the chosen model accepts. Same shape as
Content Studio's `run_content_pipeline` but for chat.

---

## 4. Medical / legal doc analysis with the embed + rerank VL models

The four retrieval models are **not chat models** — they enable RAG:
- `nvidia/llama-nemotron-embed-vl-1b-v2:free` (`or-emb`) — multimodal embed (image/text/combined).
- `nvidia/nemotron-3-embed-1b:free` (`or-emb3` / `nv-emb3`) — text embed.
- `nvidia/llama-nemotron-rerank-vl-1b-v2:free` (`or-rer`) — multimodal cross-encoder rerank.

Pipeline (the NVIDIA-recommended two-stage pattern):
1. Chunk the medical/legal docs; embed pages with `or-emb` (or `or-emb3` for text-only).
2. Store vectors (SQLite + vector column, or a lightweight ANN store).
3. On a question: embed the query, retrieve top-k by similarity.
4. Rerank those k with `or-rer` (handles charts/tables/infographics/screenshots).
5. Feed the top 5–10 chunks to a **generation** model for a cited answer.

Generation models to pair with the retrieval layer (all in `.env`):
- `or-aion3` / `or-aion3-mini` — storytelling/voice, good for readable explanations.
- `or-ds-pro` / `ds4pro` — strong analytical JSON, reliable for structured extraction.
- `or-qwen37` — cheap, solid general reasoning.
- `or-neul3` / `or-nesu3` / `or-nena3` — Nemotron Ultra/Super/Nano, long-context
  multi-turn, good for thick document threads.

Optionally point the personal agent's RAG at the same OpenKB wiki (vectorless retrieval)
so saved knowledge doubles as the document store. Net: embed+rerank = retrieval layer;
a chat/reasoning model = answer layer.

---

## 5. Other agents to build (commercial + local), with `.env` models/routers

### Commercial (billable) agents
- **Legal / Medical document reviewer** (see §4). Retrieval: `or-emb` + `or-rer`;
  generation: `or-ds-pro` or `or-neul3`. High-value, defensible upsell.
- **Meeting / Call intelligence**: audio/video in → transcript (`nv-omni` / `or-inkl`) →
  summary + action items + CRM notes (Content Studio-style output). Router:
  `multimodal_panel` = `[nv-omni, or-mimo25pro, or-ge4]`.
- **Invoice / Contract extractor**: docs → structured JSON (`or-ds-pro`, `or-nesu3`,
  `or-qwen37`); feeds bookkeeping. Pair with the §4 rerank for messy scanned PDFs.
- **Voice-of-customer miner**: social-listen + support exports → themes/trends. Reuse
  Social Listen + Brain; summarize with `or-aion3-mini` / `or-qwen37`.
- **SEO / Content gap analyzer**: given a site + keywords → briefs. Reuse Content Studio +
  Lead Finder discovery; generation `or-aion3` + `or-qwen37`.
- **Agent orchestrator / "chief of staff"**: routes a task to the best sub-agent
  (coder, planner, content, legal). Seed from `personal-planner` (mode=high); uses
  `or-neul3` / `or-nesu3` for the routing/reasoning step.

### Local / private agents (free NVIDIA NIM — "your data never leaves the machine")
- **Local coding assistant**: `nv-laguna` (= `poolside/laguna-xs-2.1`, already the `coder`
  agent's model). Router: `coding_panel` = `[nv-laguna, or-kat-coder-air-v2-5,
  or-kat-coder-pro-v2-5]`.
- **Local doc Q&A**: embed (`nv-emb3`) + rerank (`or-rer`) + answer (`nv-laguna`).
- **Private note summarizer**: `nv-laguna` / `or-neul3` (long context).
- **Private multimodal assistant**: `nv-omni` for image/video/audio locally.

### Model/router quick-reference (from `.env`)
- Coding / tool-use: `nv-laguna`, `or-kat-coder-air-v2-5`, `or-kat-coder-pro-v2-5`,
  `or-kimi27` (kimi-k2.7-code).
- Strong analytical / JSON: `or-ds-pro`, `ds4pro`, `or-nesu3`, `or-neul3`.
- Storytelling / voice: `or-aion3`, `or-aion3-mini`.
- Cheap general: `or-qwen37`, `or-qwen36`, `or-qwen35`, `or-glm` / `nv-glm52`,
  `or-mistr35` / `nv-mistr35`, `or-m3` / `nv-m3` (minimax-m3).
- Multimodal (image/video/audio): `nv-omni` / `or-omni`, `or-mimo25` / `or-mimo25pro`,
  `or-ge4` / `or-ge4free`, `or-inkl` / `nv-inkl`, `or-perc-mk1`, `or-hy3`.
- Long-context multi-turn: `or-neul3` / `or-nesu3` / `or-nena3`, `oa-sol` / `oa-terra` /
  `oa-luna` (OpenAI 2.5M context).
- Retrieval (RAG): `or-emb` (VL embed), `or-emb3` / `nv-emb3` (text embed), `or-rer` (VL rerank).
- Free/paid ladders: `or-ds-flash-free` → `nv-ds4flfree` → `ds4flash` /
  `or-ds-flash` → `or-ds-pro`; `or-ge4free` → `or-ge4`; `or-aion3-mini` → `or-aion3`;
  `or-nena3-free` → `or-nena3`; `or-nesu3-free` → `or-nesu3`; `or-neul3-free` → `or-neul3`;
  `nv-omni` (free omni) as the local multimodal default.

---

## 6. Frontend UX for public use

Current UI is a flat tab list + textareas — fine for dev, weak for product. For top-notch UX:

- **Workspace metaphor**: left sidebar (agents / threads) + main conversation/canvas, like
  ChatGPT/Claude. Each agent = a persistent thread.
- **Unified composer** accepting text + drag-drop files/images/audio/video, with attachment
  chips + previews (enables §3 multimodal input directly).
- **Rich, copyable result blocks** (not raw `<pre>`), with inline one-click "Send to…"
  actions (to Wan, Content Studio, Brain) — generalize the existing `studioSeed`/`wanSeed`
  seed pattern into a small store.
- **Streaming responses** (token-by-token) instead of waiting for the full call — big
  perceived-speed win and mitigates the slow-model frustration from the editorial saga.
- **Mode/cost toggle** per message or per agent, with a live credit/cost indicator.
- **Brain as an always-available right drawer** (search your KB without leaving chat)
  instead of a separate tab.
- **Theming + responsive layout** + empty-states/onboarding so a new user knows what each
  agent does.
- **Honest error/loading states** (you already surface "canceled" / partial) — keep that.

Architecturally: a component library (shadcn-style) + a small state layer (replace the
current prop-drilling with a store). The backend is already agent-agnostic, so the frontend
stays a thin shell over `/agents/{id}/chat`, `/brain/*`, `/social/*`, etc.

---

## Optimisations and Future builds

### A. Reuse CloakBrowser across agents (job-hunting agent)
- One cloakbrowser *installation* serves all agents; each agent gets its **own profile dir**
  (`social_profile_dir` vs a new `job_profile_dir`) reusing the same `launch_persistent_context`.
- A **job-hunting agent** (`backend/jobs/`, like `backend/social/`) can auto-find + apply on
  Upwork / Freelancer: search → filter by pre-set criteria → open → fill proposal → attach CV →
  submit, using the same BeautifulSoup/DOM pattern as Social Listen.
- Caveats: (1) authenticated *writes* carry higher ToS/ban risk than read-only scraping — throttle
  + humanize; (2) concurrent agents must not share one profile/instance → separate profile dirs;
  (3) prefer a **human-in-the-loop "review before submit"** step over fully autonomous firing.
- Net: same tool, separate profile, separate module + `JobQuery`/`JobApplication` DB models.

### B. Complementary browser/agent tooling (open source, no subscription)
- **Lightpanda** (headless engine, Zig): lightweight/fast/low-RAM scraping backend. Swap into
  `url_reader` + Lead Finder discovery for high-volume *anonymous* reads (replaces HTTP+BS4 where
  stealth login isn't needed). Not a stealth-authed replacement for CloakBrowser.
- **AgentOS** (rivet): agent *orchestration* runtime (deploy/manage/observe agents, tools, memory)
  — infrastructure layer for many agents; complements, not replaces, CloakBrowser.
- **surf-cli**: natural-language browser-task CLI — quick agentic automation shortcut; less control
  than raw CloakBrowser for stealth.
- They're complementary: CloakBrowser = authenticated/stealth read+write; Lightpanda = cheap bulk
  scrape; AgentOS = orchestration; surf-cli = fast task scripting.

### C. TimesFM time-series forecasting agent (local, free, open source)
- `google-research/timesfm`: decoder-only zero-shot forecasting foundation model (probabilistic,
  no training). `pip install timesfm`, runs CPU/GPU — no API key, no token cost.
- Build `backend/forecast/`: ingest historical series → forecast horizon + uncertainty bands → a
  chat/Fusion model (`or-aion3`/`or-ds-pro`) turns numbers into insight + actions. Store series +
  forecasts in DB.
- Use cases: revenue/cash-flow/churn forecasting; Social Listen engagement/topic-momentum
  forecasting (closes loop with the Brain); Lead Finder deal/MRR velocity; credit/token-burn
  forecasting (feeds the existing budget guardrails); market/demand sensing; personal "what's
  coming" coach. Strong, differentiated, fully local capability.

---

## Recommended open-source tools (by capability + use case)

> Curated GitHub/open-source libraries that extend the agents above. Grouped by what they
> unlock; each notes everyday-life and commercial (paying-user) use cases. Most are free /
> Apache/MIT; a few are self-hosted infra. They complement — not replace — the existing
> `router.py` + `LLMClient` + OpenKB stack.

### 1. Web / agent browsing (extend CloakBrowser + Lightpanda, §B)
- **browser-use / tracer** — high-level "agent drives a browser" frameworks. Faster path to
  build the job-apply agent (§A) and meeting-intel agent (§3) than hand-rolled DOM parsing.
  *Everyday:* auto-fill forms, book tickets. *Commercial:* RPA-as-a-service, competitor
  monitoring, automated onboarding.
- **camoufox** — stealth Firefox fork (Playwright-compatible), an alternative stealth engine
  if a platform detects Chromium. *Commercial:* broader anti-detection coverage.
- **docling** (IBM) — best-in-class PDF/Office/HTML → markdown + layout/table extraction. Swap
  into `url_reader` and OpenKB ingest for far cleaner doc text than raw BS4.
  *Everyday:* turn receipts/contracts into searchable text. *Commercial:* document intake
  pipelines for legal/medical (§4).

### 2. Knowledge / RAG (extend the Brain)
- **Crawl4AI** — LLM-friendly web crawler; keeps the Brain fresh and powers Lead Finder
  discovery. *Everyday:* clip + index your reading. *Commercial:* continuous competitive intel.
- **sqlite-vec / Lantern / Chroma** — vector stores so the medical/legal RAG (§4) scales beyond
  OpenKB's folder model. *Commercial:* multi-tenant KB per paying customer.
- **Mem0 / GraphRAG** — memory layer + knowledge graphs; turns the personal agent from
  stateless chat into one that *remembers you* across sessions. *Everyday:* a second brain that
  knows your context. *Commercial:* retained, personalized assistant per user (sticky SaaS).
- **anything-llm / privateGPT** — local, private RAG chat UIs you can white-label.
  *Everyday:* ask your own files. *Commercial:* privacy-first offering ("your data stays yours").

### 3. Time-series / forecasting (extend TimesFM, §C)
- **Chronos** (Amazon) — another zero-shot forecast foundation model; ensemble with TimesFM so
  the forecast agent picks the best per series. *Commercial:* more robust predictions.
- **Prophet / statsmodels / GluonTS** — classic + probabilistic forecasters for baselines.
- **pandas / polars / duckdb** — the series plumbing (clean, join, window).
  *Everyday:* track habits, spending, sleep. *Commercial:* churn/cash-flow/MRR forecasting.

### 4. Agents / orchestration (extend AgentOS, §B)
- **LangGraph / PydanticAI / Agno / AutoGen / smolagents** — structured runtimes with
  tool-calling, memory, guardrails. Your `router.py` already does part of this; these save
  months at scale. *Commercial:* reliable multi-step agent products.
- **n8n** — open-source visual workflow automation; glue between agents, the Brain, and SaaS.
  *Everyday:* "when I get a LinkedIn DM, draft a reply." *Commercial:* sell automations.

### 5. Media / multimodal (extend §3)
- **faster-whisper / Whisper** — local audio/video → transcript (free, no API). Feeds the
  meeting-intel agent. *Everyday:* transcribe voice notes. *Commercial:* meeting minutes.
- **ComfyUI / diffusers** — image/video generation, so Content Studio actually *produces*
  assets, not just prompts. *Everyday:* avatar/thumbnail maker. *Commercial:* on-demand
  creative factory.
- **OCRmyOCR / EasyOCR** — scanned-doc text for the legal/medical agent. *Commercial:* intake.

### 6. Personal / productivity (the "Personal Secretary" everyone pays for)
- **cal.com API / Microsoft Graph / Google APIs** — calendar/email/contacts integration.
  *Everyday:* "schedule the dentist and email mom." *Commercial:* executive-assistant tier.
- **Obsidian** — the Brain's wiki is already Obsidian-compatible; surface it as the user's
  knowledge home. *Commercial:* "your second brain" product.
- **localtonet / tailscale** — expose a local agent securely to the user's phone.
  *Everyday:* use your agent from anywhere. *Commercial:* managed private deployment.

### 7. Infra / cost control (you already care about token burn)
- **LiteLLM** — central model gateway with caching, fallbacks, and **spend tracking across all
  providers**. The natural home for the free→paid ladder (§2). *Commercial:* per-user budgets.
- **Opik / Phoenix (Arize) / LangSmith** — LLM observability/tracing; directly addresses the
  runaway-cost pain from the editorial saga. *Commercial:* SLA/quality dashboards for clients.
- **Langfuse** — tracing + prompt versioning + evals. *Commercial:* prove quality to buyers.

### 8. Everyday-life standouts worth featuring
- **Home Assistant** (integrations hub) — agent controls smart home. *Commercial:* concierge tier.
- **Huginn** — "IFTTT for hackers," self-hosted; lightweight personal automations.
- **bookstack / wiki.js** — nice front-end for the Brain KB.
- **Silverbullet / SiYuan** — local-first note spaces that pair with Mem0/GraphRAG.

### How to prioritize (suggested build order)
1. **docling** + **Crawl4AI** → better Brain ingest (quick win, reuses §4/§B).
2. **LiteLLM + Opik** → cost guardrails + observability (directly fixes past pain).
3. **Mem0 / GraphRAG** → memory personal agent (differentiator, sticky).
4. **browser-use + camoufox** → job-apply / RPA agents (§A).
5. **TimesFM + Chronos** → forecast agent (§C).
6. **ComfyUI / Whisper / calendar APIs** → rich multimodal personal assistant.

> Rule of thumb: prefer tools that are (a) self-hostable (privacy selling point), (b) free or
> per-GPU (no per-seat tax), and (c) drop-in behind `router.py` so the model-ladder (§2) still
> governs cost. Features that touch the user's *own* data (Brain, calendar, memory) are the
> most defensible paid tiers.
