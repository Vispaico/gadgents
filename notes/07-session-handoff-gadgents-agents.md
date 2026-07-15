# Gadgents — Agent Build Session Handoff #2 (recap + next steps)

> Read this FIRST in the next chat. All code on disk is the source of truth; this recap
> is just so we continue seamlessly. The previous handoff (notes/06-...) covered the first
> agent-build session; this one continues from there and is the current state. We started a
> fresh chat the same way (read the handoff, then the todo list reflects real state).
>
> CONTEXT: this thread reached ~77% of its context window. Start a NEW chat, re-read this
> file, then `git status` / `git log`. Keep using notes/07 as the single source of continuity.

## Recent changes since the initial #2 write (mode toggle + tuning kickoff)
- ADDED global **quality/cost mode toggle** in the frontend header (Quality / Balanced /
  Economic) → sends `?mode=` on every agent call. Backend: `run_agent` gained `override_mode`
  (swaps Fusion preset when forced) and `override_model` (race-free per-call model pin swap).
  Applied as a query param on `/agents/{id}/chat`, `/repurposer/run`, `/leadfinder/run`,
  `/wan/run`, `/pipeline/content`. Single-model pins (coder, prompt-engineer, content-producer)
  keep their pins UNLESS explicitly overridden.
- CONTENT STUDIO now honors the toggle via per-mode stage-2 model in `backend/pipeline.py`
  `CONTENT_PRODUCER_MODEL_BY_MODE`:
  * prompt-engineer stays `or-qwen37` in all modes.
  * content-producer: Economic = `or-llama33` (cheap, current default), Balanced = `or-sonnet46`
    (claude-sonnet-4.6), Quality = `or-opus` (claude-opus-4.8).
  User confirmed Quality output > Balanced at same cost for Content Studio; chose to keep
  Content Studio's toggle meaningful (quality = opus, balanced = sonnet, economic = llama).
- ADDED React Error Boundary in `frontend/src/main.jsx` so render crashes show the error
  instead of a black screen.
- ADDED `GET /api/config` returning `require_login`/`enable_paywall`/`providers`; frontend
  skips the login screen in dev-bypass mode (synthetic dev user).

## Bugs fixed this session (important — some were silent until tested in browser)
1. Frontend `ModeToggle` called `getMode()` but only `setMode` was imported →
   `ReferenceError: getMode is not defined` → black screen. FIX: import `getMode` in App.jsx.
2. `/api/pipeline/content` returned **422** — FastAPI auto-wrapped the single Pydantic body
   model, so it expected `{payload:{...}}` while frontend sends flat `{material,platforms}`.
   FIX: split into `material` + `platforms` as `Body(..., embed=True)`.
3. Pipeline crashed on `user.credits` when `user is None` (dev-bypass). FIX:
   `user.credits if user else 0`. (`charge()` already no-ops when paywall off.)
4. Stale dev server: an old `npm run dev` held :5173 → black screen. Always restart via
   `./dev.sh` (it falls back to :5174 if :5173 busy) and hard-refresh.

## Model routing cheat-sheet (where the toggle actually bites)
- Single-model pinned agents (their pins DON'T change with the toggle): `prompt-engineer`
  (or-qwen37), `content-producer` (or-llama33 base, but Content Studio overrides per mode),
  `coder` (oa-codex), `lead-finder` chat wizard (or-sonnet46).
- Mode-driven (non-pinned): `personal-planner` (mode=high), `lead-finder` audit (or-sonnet46),
  scoring (or-llama33). These honor `override_mode` for `goal`.
- Fusion agents honor `override_mode` by swapping to `_FUSION_PRESETS[mode]`:
  content-repurposer & wan-video (default custom panels) + lead-finder ICP stage.
- Default Fusion presets: high `[or-opus,or-kimi,or-ds-pro,oa-sol]`/judge or-opus ·
  mixed `[or-sonnet46,or-qwen37,oa-luna]`/judge or-sonnet5 ·
  economic `[or-ds-flash-free,or-haiku,oa-nano]`/judge or-haiku.



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

## Session update (2026-07-13) — Content Studio 3-mode eval
- User ran Content Studio in Economic/Balanced/Quality on the SAME literary article and
  had the three outputs blindly evaluated. Winner: Quality (9.7) > Balanced (8.9) > Economic (7.7).
- Key finding: stage-1 `prompt-engineer` output is identical across modes (pinned `or-qwen37`
  by design — `pipeline.py` calls stage 1 with NO override). The visible quality gap is
  entirely stage-2 `content-producer` (or-llama33 vs or-sonnet46 vs or-opus). The eval's
  "Prompt quality" row is largely misattributed: the evaluator read the final content (stage 2)
  and credited the prompt. Temperature is 0.7 (no seed) in `llm.py`, so even identical qwen37
  runs vary run-to-run, but cannot systematically correlate with the mode label.
- Decision: KEEP `prompt-engineer` pinned to `or-qwen37`. The Quality/Cost toggle is meaningful
  only through stage-2. No code change.
- Takeaway for tuning: if a user later wants the *prompts themselves* to scale with the toggle,
  add `CONTENT_PROMPT_ENGINEER_MODEL_BY_MODE` (mirror `CONTENT_PRODUCER_MODEL_BY_MODE`) — not
  built, defined as a future hook only.

## Session update (2026-07-13, part 2) — Content agent consolidation
- User wanted `prompt-engineer`, `content-producer`, `content-repurposer` removed from the
  Bots page and consolidated into the Content Studio, with a choosable output mode and a
  "Send to Wan" button. Decisions: THREE discrete radio modes (Prompts / Content+Media /
  Repurpose), and a "Send to Wan Video" button on the prompts result.
- Backend changes:
  * `AgentDef` gained `show_in_bots: bool = True`. `list_production_agents()` unchanged;
    added `list_bot_agents()` (production + show_in_bots). `routes/agents.py` now uses
    `list_bot_agents()`, so the 3 content agents no longer appear as cards (verified:
    /api/agents returns only coder, personal-planner, lead-finder, wan-video).
  * The 3 agents keep `production_ready=True` + `show_in_bots=False` so they still power
    the Studio. No agent removed from REGISTRY.
  * `pipeline.py run_content_pipeline` gained `output_mode` param: "prompts" (stage-1 only),
    "content" (default 2-stage), "repurpose" (delegates to `content-repurposer` Fusion agent;
    platform labels mapped to its channel ids). `routes/pipeline.py` accepts `output_mode`.
    Mode toggle flows through all three (prompts pins qwen37; repurpose honors override_mode).
- Frontend changes:
  * `api.pipeline` now passes `output_mode`.
  * `ContentStudio` rewritten: radio `output-modes` (Prompts / Content+Media / Repurpose),
    platform chips, and a "→ Send prompts to Wan Video" link on prompt results.
  * `Home` holds `wanSeed` state; selecting Wan tab seeds `WanVideo` concept with the prompts.
  * Added `.output-modes` CSS.
- Verified: backend imports OK, /api/agents filtered, /api/pipeline/content with
  output_mode=repurpose + prompts both parse and return 200 (live OpenRouter call succeeded).
  Frontend `npm run build` passes.
- NOTE: repurposer currently still persists briefs in `routes/repurposer.py` at /api/repurposer.
  We did NOT wire the Studio "Repurpose" mode to that persistence path — it calls the agent
  directly via the pipeline. The /api/repurposer/run route is now somewhat redundant; left as-is.
  If user wants Repurpose runs saved to history, route the pipeline repurpose through
  repurposer.py instead of calling the agent inline.

## Session update (2026-07-14) — Content Studio now accepts URLs/links
- User asked: in Content Studio, allow pasting article/blog URLs so the model reads + repurposes
  (or rewrites plagiarism-free / creates Content+Media posts) from link content, not just pasted text.
- Added `backend/url_reader.py` (new): `read_urls(urls)` reuses existing web-fetch building blocks
  from `backend/leads/discovery` — Firecrawl markdown via `_fc_scrape` when configured/reachable,
  else plain HTTP `_request` + BeautifulSoup fallback (strips scripts/style/chrome). Public-web only,
  GDPR-safe. Caps 12k chars/URL, 40k total to protect prompt context. Prepend "=== Content read from
  the provided URLs ===" block to the material.
- Wiring: `run_content_pipeline` gained `urls: list[str]` param; `routes/pipeline.py` accepts
  `urls: list[str] = Body([])`; frontend `ContentStudio` has a 2nd textarea for URLs (one per line or
  space/comma separated, `parseUrls()`), run() passes them. Works for ALL three output modes
  (prompts/content/repurpose). `api.pipeline` signature updated.
- Verified: backend imports ok; `read_urls(['https://example.com'])` returns 178 chars of readable
  text via the HTTP fallback (Firecrawl not up). Frontend `npm run build` passes.
- NOTE: URLs are appended to material and the LLM is instructed (via existing agent prompts) to
  preserve source voice / not invent facts; "rewrite free of plagiarism" is a property of the agent
  prompts (no explicit anti-plagiarism step). Good enough for the use case; could add an explicit
  "rewrite in your own words" instruction later if needed.

## Session update (2026-07-14, part 2) — dedicated Instructions field in Content Studio
- User confirmed: add a SEPARATE "Instructions / style notes" input (so guidance isn't mixed into
  the source material field and misread as text to preserve). Added `instructions` textarea in
  `ContentStudio` (optional, below URLs). Run triggers if material OR urls OR instructions is filled.
- Backend: `run_content_pipeline` + `routes/pipeline.py` accept `instructions: str`. Injected into
  stage-1, stage-2 AND repurpose prompts as a clearly labeled block:
  "EXPLICIT INSTRUCTIONS (you MUST follow these, they are not source content)" so the model treats
  it as commands. `api.pipeline` signature updated to pass it.
- Verified: frontend `npm run build` passes; backend (pipeline + routes) imports ok.
- Handoff continuity: always append session updates here at each boundary so a fresh chat can resume.

## Session update (2026-07-14, part 3) — Repurpose persistence history wired up
- User asked to wire the repurposer persistence history (Studio Repurpose mode was ephemeral;
  the old `/api/repurposer/run` + `/briefs` route still persisted but was orphaned/no longer called).
- Decisions: (1) persist in dev-bypass mode under a synthetic dev-user so history works NOW;
  (2) REMOVE the orphaned repurposer route entirely, fold persistence into the pipeline;
  (3) parse repurposer JSON into per-channel ContentOutput rows (rich history).
- Backend changes:
  * `backend/db.py`: added `get_or_create_dev_user(session)` (synthetic `__dev__@gadgents.local`,
    only created in bypass mode) so history persists without a real login.
  * `backend/pipeline.py`: imports ContentBrief/ContentOutput/get_or_create_dev_user; added
    `_resolve_user()` (real or synthetic dev user) and `_persist_repurpose()` (parses JSON, writes
    ContentBrief + per-channel ContentOutput for posts + script + media_suggestions). Repurpose
    branch now persists + returns `brief_id`.
  * `backend/routes/pipeline.py`: `ContentOut` gained `brief_id`; added `GET /api/pipeline/briefs`
    (lists user's or synthetic dev user's briefs, newest first).
  * `backend/routes/repurposer.py`: DELETED (orphaned). Removed from `app.py` (router include +
    lifespan close). `close_repurposer_llm` no longer referenced anywhere (verified).
- Frontend changes:
  * `api.js`: added `pipelineBriefs()`. `ContentStudio` now has `past` state, loads briefs on mount
    (when in repurpose mode) and after a repurpose run, and renders a "Past Repurpose runs" grid.
- Verified: `npm run build` passes. Backend imports ok. Direct unit test (mocked repurposer JSON)
  created 1 ContentBrief + 4 ContentOutput rows (linkedin, instagram, media, script) with dev user.
  Live boot: `/api/config`, `/api/pipeline/briefs` both respond (empty list initially, fills after runs).

## Session update (2026-07-14, part 4) — Repurpose history cards are clickable
- User asked to make the "Past Repurpose runs" cards open their stored content.
- Backend: added `GET /api/pipeline/briefs/{brief_id}` returning the brief + all its
  ContentOutput rows (channel, content_json, model). 404 if missing or not the user's.
  Imported ContentOutput into the route.
- Frontend: `api.pipelineBrief(id)`; `ContentStudio` tracks `openBrief`; history cards are
  clickable (`openBriefById`), showing a detail view (brief_json + per-output cards w/ channel
  badge + "← Back to runs"). Added `.brief-detail` CSS.
- Verified: frontend build passes; backend (routes.pipeline, app) imports ok. Live boot returns
  [] for list and 404 for unknown brief id.

## Next steps (per original plan + where we are)
- PER-AGENT TUNING (in progress): adjust `router_model` pins / `mode` / Fusion usage per
  agent. DONE FIRST: Content Studio per-mode mapping (see Recent changes). Still to do / user
  feedback pending:
  * lead-finder ICP stage already Fusion; audit uses `or-sonnet46` (cheap), scoring
    `or-llama33`. Possibly raise scoring to a stronger model. User hasn't tested Lead Finder
    outputs yet.
  * wan-video Fusion panel is heavy (4 models incl or-opus x2); consider economic preset for
    drafts. User hasn't tested Wan outputs yet.
  * personal-planner mode=high already.
  * coder stays pinned oa-codex (intentional; toggle won't change it).
  * Decide whether OTHER single-model agents should also honor the toggle (currently only
    Content Studio stage-2 maps per mode; prompt-engineer/coder keep fixed pins by design).
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
When a chat's context approaches ~70–80%, START A NEW CHAT, re-read notes/07 (this file) first,
then run `git status`/`git log` and the agent-registry one-liner above. This thread hit ~77% and
was handed off this way. The handoff doc is the single source of continuity; keep it updated at
each session boundary (append to "Recent changes" and refresh the bugs/next-steps as needed).

## Session update (2026-07-14, part 5) — social-listener agent (CloakBrowser) scoped
- User wants an agent that pulls posts from X + LinkedIn by topic, sorts by engagement
  (likes/reach), and offers one-click repurpose into Content Studio. Accepted CloakBrowser
  despite ToS/ban risk; chose "discuss more, don't build yet" then clarified **reach sort is
  NOT important** (only likes/engagement matters) -> removes the one hard constraint.
- CORRECTION to older handoff line "CloakBrowser = overkill/ToS risk": it is NOT overkill;
  it's the correct stealth-Chromium (Playwright drop-in, 66 source-level fingerprint patches,
  passes Cloudflare/FingerprintJS/BrowserScan). Overkill half was wrong. ToS risk remains real
  but comes from the *action* (reading another platform's posts via authenticated session),
  not the tool. Target: `pip install cloakbrowser[geoip]`, persistent logged-in profile,
  `humanize=True`, residential proxy. NOTE macOS stuck on older free v146 build; v148+ needs Pro sub.
- Engagement reachability via scraping: X likes/retweets/replies ARE in DOM (sortable). LinkedIn
  gives likes at best (impressions/reach are author-only, never in DOM). With "reach not needed",
  X is fully sortable; LinkedIn = likes-sort-with-caveat (higher ban risk even with stealth).
- Planned architecture (NOT yet built):
  * `backend/social/` module: CloakBrowser client wrapper (topic query -> rendered DOM ->
    SocialPost extraction); `SocialQuery` + `SocialPost` DB models (platform, author, text,
    like_count, repost_count, reply_count, url, query_id) following ContentBrief/ContentOutput pattern.
  * Frontend: new "Social Listen" tab — topic input, X/LinkedIn toggle, sorted feed, per-post
    "Repurpose" button seeding Content Studio `material` (reuse Wan-tab seed pattern).
  * Content Studio reuse is trivial: it already accepts `material`; a repurposed post == material.
- Status: SCOPED ONLY. No code written yet. Awaiting user go-ahead to scaffold `backend/social/`.

## Session update (2026-07-14, part 6) — social-listener agent BUILT
- User said "build it, then update the handoff." Implemented the full agent #5.
- `backend/db.py`: added `SocialQuery` (user_id, topic, platforms csv, created_at) and
  `SocialPost` (query_id, user_id, platform, author, text, like_count, repost_count,
  reply_count, url). `init_db()` creates them (verified).
- `backend/config.py`: added `cloakbrowser_license_key`, `social_proxy`,
  `social_profile_dir` (CloakBrowser session/profile/proxy config).
- `backend/social/__init__.py` (NEW): CloakBrowser client. `cloakbrowser` is a LAZY import
  (only when a listen runs) so the app boots without it. `listen_x`/`listen_linkedin` parse
  rendered DOM via BeautifulSoup; `_parse_count` handles 1.2K/3.4M; results sorted by likes
  desc. Listener failures surface as one "[scrape failed: ...]" post (UI-warns, doesn't crash).
  `listen(platforms, topic, limit)` merges + platform-tags + sorts.
- `backend/routes/social.py` (NEW): `POST /api/social/listen` (persists query + posts, returns
  posts), `GET /api/social/queries`, `GET /api/social/queries/{id}/posts` (sorted by likes).
  Uses `get_or_create_dev_user` so history works in dev-bypass. Registered in `app.py`.
- Frontend: `api.socialListen/socialQueries/socialPosts`; new **Social Listen** nav tab;
  `SocialListen` component (topic input, X/LinkedIn toggle, engagement-sorted feed with
  like/repost/reply counts + View/Repurpose links, Past listens grid). Per-post "→ Repurpose"
  seeds Content Studio `material` (reuses the seed pattern; `Home` gained `studioSeed` state,
  `ContentStudio` accepts `seed`). Same pattern already used for Wan `wanSeed`.
- Verified: frontend `npm run build` passes; backend (app, routes.social, db init) all ok;
  `GET /api/social/queries` returns 200 `[]` via TestClient with no cloakbrowser installed.
- NOT YET TESTED LIVE: actual X/LinkedIn scraping needs cloakbrowser installed + a real
  logged-in persistent profile in `social_profile_dir` + (recommended) a residential
  `social_proxy`. macOS is on free v146 build; v148+ needs Pro `cloakbrowser_license_key`.
- REMINDER for next chat: do not run a real listen without a configured profile; it will fail
  gracefully (lazy ImportError surfaced as a failed post).

## Session update (2026-07-15) — social-listener setup docs added
- User asked for a README/setup note for the CloakBrowser profile. Added:
  * `notes/08-social-listener-setup.md` — install (`pip install cloakbrowser[geoip]`), how to
    seed a persistent logged-in profile (headed launch + manual login, or copy a Chrome profile),
    `.env` keys (SOCIAL_PROFILE_DIR / SOCIAL_PROXY / CLOAKBROWSER_LICENSE_KEY), run/verify,
    ToS+ban-risk callout, and the 3 endpoints.
  * `.env.example`: documented the three SOCIAL_*/CLOAKBROWSER_* keys with comments (free v146 vs
    Pro v148+ builds; macOS on free build).
- No code changes. Both docs match existing conventions (notes/ numbered, .env.example key order).

## Session update (2026-07-15, part 2) — CloakBrowser wired + X listener WORKING live
- User installed cloakbrowser and we seeded a logged-in profile. Two bugs found + fixed:
  * `_build_browser`/`seed_social_profile.py` used `launch(user_data_dir=...)` -> TypeError.
    CloakBrowser needs `launch_persistent_context(user_data_dir=...)` (returns a BrowserContext;
    use `ctx.new_page()`, `ctx.close()`). FIXED in `backend/social/__init__.py` + seeder.
  * `goto(wait_until="networkidle")` timed out on X/LinkedIn (they never idle). Changed to
    `domcontentloaded` + settle in `_wait_and_scrape` and the seeder.
  * X engagement parser was wrong (looked for data-testid metric divs). X now puts everything in
    ONE aria-label per tweet: "49 replies, 222 reposts, 1827 likes, 4722 bookmarks, 357078 views".
    FIXED `listen_x` to regex that aria-label for likes/reposts/replies.
- Verified LIVE: saved profile is logged in (X home renders, no "Log in"); `listen_x('ai agents')`
  returns real posts with correct authors + status URLs; likes parse (e.g. 6649, 1830, 476) and
  sort desc; end-to-end `POST /api/social/listen` -> 200, query persisted, `GET /api/social/queries`
  -> 200. LinkedIn listener code exists but NOT yet live-tested (needs a confirmed LinkedIn
  session in the same profile; LinkedIn DOM parsing is best-effort via aria-label "like|reaction").
- `.env` now has SOCIAL_PROFILE_DIR=/Users/n3ils/.cloakbrowser/social-profile (CLOAKBROWSER_
  LICENSE_KEY + SOCIAL_PROXY left blank; recommended to add a residential proxy later).
- 2FA note: email-code login created a session cookie that persisted; if X later forces re-auth,
  just re-run `python seed_social_profile.py`.
- To run the agent: `./dev.sh`, open Social Listen tab, enter topic + platforms, Listen.

## Session update (2026-07-15, part 3) — LinkedIn listener LIVE-tested + working
- LinkedIn listener was coded but untested. Live test found: (1) LinkedIn SEARCH results page
  lazy-loads EMPTY under stealth headless (no post DOM), so switched `listen_linkedin` to scrape
  the FEED (`/feed/`) which reliably renders. (2) Engagement is "N reactions" strings; climb to
  enclosing card (text>120) for post body. (3) Topic match is SOFT: LinkedIn feed isn't
  topic-scoped headlessly, so we rank topic-matches first then top-up with highest-reaction posts
  (don't drop everything when the feed lacks the topic). (4) Author: prefer /in/ link, else take
  text before first "•" (cosmetic noise remains on some "follows this Page" prefixes — acceptable
  for prototype).
- Verified LIVE: `listen_linkedin` returns real posts w/ reaction counts (3146, 805, 749...);
  end-to-end `POST /api/social/listen` platforms=['linkedin'] -> 200. X listener also re-confirmed.
- BOTH X + LinkedIn listeners now work against the saved profile. Remaining gaps: LinkedIn author
  prefix noise; no per-post URL on LinkedIn (none in feed DOM); no residential proxy yet.
- PROXY explanation given to user: SOCIAL_PROXY routes CloakBrowser through a residential IP to cut
  ban risk from repeated automated traffic on one home IP. Optional; not required to run.

## Session update (2026-07-15, part 4) — proxy documented + LinkedIn author tightened + relogin note
- Proxy: already wired in `backend/social/__init__.py._build_browser` (`kwargs["proxy"]` +
  `geoip=True` from `settings.social_proxy`). This session added USER-FACING PROXY DOCS:
  * `.env.example` social_proxy comment now shows exact URL format
    (`http://user:pass@host:port` or `socks5://...`). `.env` SOCIAL_PROXY left blank (no provider yet).
  * New `notes/09-social-relogin.md`: full re-login procedure — when to re-login (0 posts /
    login wall), a headless check snippet, exact terminal steps (`cd` -> `source .venv/bin/activate`
    -> `python seed_social_profile.py`, headed window, log in X then LinkedIn, press ENTER each),
    why `launch_persistent_context` (not `launch`), why `domcontentloaded` not `networkidle`,
    how to re-login one platform, proxy setup, and post-relogin verification.
- LinkedIn author tightening: previously captured noisy prefixes ("Niels Teitge follows this
  Page LinkedIn for Marketing 5,450,..."). Rewrote author logic in `listen_linkedin` to prefer
  the in-card `/in/` link's visible text up to "•", else the slug; fallback to text-before-"•".
  Verified: authors now clean ("Rbranson", "Candice Odgers", "BBC News 16h"); residual edge case
  is follower-recommendation cards (acceptable).
- Verified: backend imports OK; listen_linkedin returns real posts w/ clean authors + reactions.
- No proxy VALUE set (needs a purchased residential proxy). Code path confirmed correct.

## Session update (2026-07-15, part 5) — Editorial AI Studio DESIGNED (not built)
- User wants a "Content Engine" (VISPAICO Media Engine / Editorial AI Studio): from ONE essay,
  mine ideas -> plan -> create platform-native assets (LinkedIn/FB/IG/X/Newsletter/YT Shorts/
  YT long 3-10m/Podcast 2-host 1-5m + Quotes/Hooks/Questions/Predictions), 4 versions each,
  humanized + quality-scored, with a brand link (default https://www.vispaico.com/en/aios)
  injected naturally, NO AI tells. Full 6-stage spec came from the user's research (Idea Miner,
  Strategist, Creator, Humanizer, Quality Director, Multiplier) + deferred Audience Intelligence
  Editor. Must adapt to ANY brand voice (not hardcoded).
- DECISION/RECOMMENDATION captured in **notes/10-editorial-ai-studio.md**: do NOT build a flat
  prompt library. Build a staged orchestration (agent #6) that REUSES + EXTENDS existing agents
  (content-repurposer, prompt-engineer, Fusion router) and persists intermediate artifacts. The
  ONLY "prompt library" piece = 6 editable `PromptTemplate` rows. Brand voice = a `BrandProfile`
  (link + voice + forbidden phrases) injected via the `_instructions_block` pattern we built for
  Content Studio, so it adapts to any brand. Quality principle honored: ONE idea per creation,
  4 versions, never one mega-prompt (maps to per-call run_agent).
- Design includes: 6 new editorial agents, DB models (BrandProfile, EditorialRun, IdeaBank,
  EditorialCalendar, EditorialAsset, PromptTemplate), `backend/editorial.py` pipeline, route
  `/api/editorial/*`, frontend Editorial Studio tab. Open decisions listed in the note (new tab
  vs 4th mode; ship stages 1-5 first; brand defaults; assets editable; extend vs new creator).
- STATUS: DESIGNED ONLY. No code written yet. NOT built this session — user wanted the design +
  handoff before next chat. (.env still REQUIRE_LOGIN=false; backend not running.)

## Next steps (per original plan + where we are)
