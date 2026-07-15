# Editorial AI Studio — design (agent #6, multi-stage content engine)

Scoped from a user conversation. Builds on the existing Content Studio / repurposer. NOT a flat
"prompt library" — it's a staged orchestration that reuses + extends current agents, persists
intermediate artifacts, and injects a pluggable brand voice (adapts to ANY brand, not just
Vispaico). The full 6-stage spec (Idea Miner → Strategist → Creator → Humanizer → Quality
Director → Multiplier) + Audience Intelligence Editor came from the user's research; this note
maps it onto the Gadgents codebase and decides the implementation shape.

## Why not a prompt library?
- The value is the **state machine**: Stage 2 consumes Stage 1's output; Stage 3 creates ONE
  idea at a time (quality lever); Stage 4/5 refine. A library of prompt strings has no state.
- It must **persist** the idea bank + calendar + created assets (so a run is resumable/editable).
- It must **reuse** existing agents (`content-repurposer` already does multi-platform + media +
  script JSON) and the Fusion router.
- Brand voice must be a **parameter**, not hardcoded text.
Where a library DOES fit: store the 6 stage SYSTEM PROMPTS as editable, versioned templates
(`PromptTemplate` table) so they're tunable without code edits. That's the only "library" piece.

## Core quality principle (from the spec — do NOT skip)
> "Create content ONLY for the SELECTED idea. Never reference the original essay. Write as
> though created independently." + generate ONE idea per creation, 4 versions each.
The orchestrator loops per selected idea × per platform. Never one mega-prompt for the whole
essay (GPT-class models lose quality across that volume). This maps perfectly to our existing
per-call `run_agent` + Fusion design.

## Mapping to existing codebase
- `backend/agents.py` `agent()` factory — register 6 new editorial agents (below). Same pattern
  as `content-repurposer` (Fusion) / `prompt-engineer` (pinned).
- `backend/pipeline.py` `run_content_pipeline` — the template to mirror. New
  `backend/editorial.py` `run_editorial_pipeline(session, user, essay, brand_id, ...)` chains
  the 6 stages, persisting between them.
- `backend/routes/pipeline.py` + `app.py` — add `backend/routes/editorial.py`, register router.
- `backend/db.py` — new models (below).
- Frontend `App.jsx` — new **Editorial Studio** tab (or a 4th Content Studio output mode
  "Editorial Engine"; DECISION for next chat — see bottom).
- Brand voice: reuse the `instructions` injection pattern we built for Content Studio
  (`_instructions_block`). A `BrandProfile` carries voice/link/forbidden-phrases and is injected
  as instructions into Stages 3/4/5. This is what makes it adapt to any brand.

## The 6 stages → agents
1. **editorial-idea-miner** (single strong model, e.g. or-opus; no Fusion needed) — extracts
   25–50 ideas as JSON (title, summary, scores, platform potentials). Returns `IdeaBank`.
2. **editorial-strategist** (or-opus) — picks 6–12, diversifies, builds 4-week calendar
   (Markdown/JSON). Consumes IdeaBank.
3. **editorial-creator** (Fusion, extends `content-repurposer`) — for EACH selected idea, emits
   platform-native assets: LinkedIn(4), FB(4), IG carousels(4), X threads(4), Newsletter(4),
   YouTube Shorts(4), YouTube long(4, 3–10min), Podcast(4, 2-host, 1–5min), Quotes(10),
   Hooks(20), Questions(10), Predictions(10). Naturally references the brand link (injected via
   BrandProfile) without being promo. Persists `EditorialAsset` rows.
4. **editorial-humanizer** (or-opus) — strips AI tells (rhythm, clichés, jargon). Per asset.
5. **editorial-quality-director** (Fusion judge, or-opus) — scores 1–10 across 14 dims, rewrites
   until ≥9.5. Per asset.
6. **editorial-multiplier** (or-opus) — proposes new IP (essays, videos, talks…). Optional.

   + **Audience Intelligence Editor** (FUTURE, deferred) — ingests platform analytics, updates
     the BrandProfile/"Editorial Constitution". Needs analytics sources; out of scope for v1.

## New DB models (`backend/db.py`)
- `BrandProfile` (id, name, voice_prompt, link_url, forbidden_phrases, is_default) — the
  pluggable brand. Default seeded for Vispaico (link https://www.vispaico.com/en/aios).
- `EditorialRun` (id, user_id, brand_id, essay_text, status, created_at).
- `IdeaBank` (id, run_id, ideas_json) — Stage 1 output.
- `EditorialCalendar` (id, run_id, calendar_json) — Stage 2 output.
- `EditorialAsset` (id, run_id, idea_ref, platform, version, kind, content, humanized,
  quality_score, created_at) — Stage 3–5 outputs, one row per version.
- `PromptTemplate` (id, stage, version, system_prompt, updated_at) — the editable stage prompts
  (the only "prompt library" piece).

## Orchestration shape (`backend/editorial.py`)
```
run_editorial_pipeline(essay, brand_id, selected_platforms, limits):
  ideas   = run_agent(idea_miner, essay + brand_instructions)        -> IdeaBank
  plan    = run_agent(strategist, ideas + brand_instructions)         -> Calendar (6-12 ideas)
  for idea in plan.selected:
    for platform in selected_platforms:
      for v in 1..4:
        raw    = run_agent(creator, idea + platform + brand_instructions)
        hum    = run_agent(humanizer, raw)
        final  = run_agent(quality_director, hum)                     -> EditorialAsset
  multiplier = run_agent(multiplier, all_assets)   # optional
```
Each `run_agent` reuses `_instructions_block` (brand voice + link + "never sound AI" rules).
Mode toggle already flows through `run_agent`/`override_mode` — so the Quality/Cost switch works
here too (pin Stage 3/4/5 to strong models in Quality mode for best result).

## Route (`backend/routes/editorial.py`)
- `POST /api/editorial/run` {essay, brand_id, platforms[], mode} → runs full pipeline, returns
  run_id + assets.
- `GET  /api/editorial/runs` → past runs (dev-user aware, like pipeline briefs).
- `GET  /api/editorial/runs/{id}/assets` → assets for a run (sorted by platform/version).
- `GET/PUT /api/editorial/brands` → list/select brand profile (link + voice).
- `GET/PUT /api/editorial/templates` → edit the 6 stage prompts (the library surface).

## Frontend
- New **Editorial Studio** tab: essay textarea (+ our existing URLs/instructions fields), brand
  selector (Vispaico default), platform multiselect, "Run Engine" → results grouped by
  platform with 4 version cards + Repurpose/export. Reuses Content Studio's UI patterns and the
  per-post Repurpose seed we built for Social Listen.
- Assets render editable (so a human can tweak before publishing) — not just display.

## Open decisions for the next chat
RESOLVED on 2026-07-15 (built; see notes/07 part 6):
1. NEW TAB — Editorial Studio is its own nav tab, Content Studio untouched.
2. Shipped STAGES 1-5; Multiplier is opt-in (checkbox), Audience Intelligence deferred.
3. BrandProfile seeded: Vispaico default (link https://www.vispaico.com/en/aios) + generic
   "Untitled Brand" fallback.
4. Assets persist as editable text (EditorialAsset.content = JSON list of versions); PATCH
   `/api/editorial/assets/{id}` edits them before publishing.
5. Separate `editorial-creator` agent (repurposer left as-is for Content Studio Repurpose).

## Verification plan (when built)
- Unit: mock LLM, assert IdeaBank JSON shape, asset row count = ideas×platforms×4.
- Live (dev): one real essay through the pipeline, check no "AI tells" + brand link present.
- Frontend build passes; `/api/editorial/run` returns assets; history lists them.
