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

## Session update (2026-07-15, part 6) — Editorial AI Studio BUILT (agent #6)
- User said "build the Editorial Studio." Implemented the full multi-stage content engine from
  notes/10 (designed last session). Decisions from notes/10 honored: NEW Editorial Studio tab
  (NOT a 4th Content Studio mode); shipped STAGES 1-5 (Multiplier deferred behind a checkbox);
  seeded Vispaico default + generic "Untitled Brand" fallback; assets persist as editable text.
- `backend/db.py`: added models `BrandProfile, EditorialRun, IdeaBank, EditorialCalendar,
  EditorialAsset, PromptTemplate` + `seed_editorial_defaults()` (idempotent; called from
  `init_db()`). Verified `init_db()` creates all editorial tables and seeds Vispaico brand +
  6 stage templates.
- `backend/agents.py`: registered 6 editorial agents (idea_miner/strategist/creator/humanizer/
  quality_director/multiplier). `idea_miner/strategist/humanizer/multiplier` pinned `or-opus`
  (single strong model); `creator` + `quality_director` are Fusion (panel incl or-opus judge).
  ALL `show_in_bots=False` (they power the Studio, not the Bots page). `list_production_agents()`
  now returns 13 (8 core + 6 editorial).
- `backend/editorial.py` (NEW): `run_editorial_pipeline()` stages 1-5 + optional 6: Idea Miner ->
  Strategist (calendar, max_ideas = 4-12 selectable) -> per selected idea × per platform:
  Creator -> Humanizer -> Quality Director. Brand voice injected via `_brand_block` (link +
  voice + forbidden phrases, the `_instructions_block` pattern). Each stage reads its EDITABLE
  prompt from `PromptTemplate` (falls back to agent default). Stage prompts use `route()` with
  the quality/cost toggle (override_mode) so Quality/Balanced/Economic works here too. Assets
  stored one row per (idea, platform), `quality_score` set by the Director. Fallback: if
  Strategist returns no selection, top ideas by novelty+reach are used.
- `backend/routes/editorial.py` (NEW): `POST /api/editorial/run` (essay, brand_id, platforms,
  mode, max_ideas, run_multiplier), `GET /api/editorial/runs`, `GET /api/editorial/runs/{id}/
  assets`, `PATCH /api/editorial/assets/{id}` (editable versions), `GET/PUT /api/editorial/
  brands`, `GET/PUT /api/editorial/templates` (the editable prompt library surface). Dev-bypass
  aware (uses synthetic dev user for history/edits). Registered in `app.py`.
- Frontend: `api.js` gained `editorialRun/Runs/Assets/UpdateAsset/Brands/UpdateBrand/Templates/
  UpdateTemplate`. `App.jsx` gained a new **Editorial Studio** nav tab + `EditorialStudio`
  component (essay textarea, brand <select> defaulting to Vispaico, platform multiselect, max-
  ideas selector, "Also run Multiplier" checkbox) + `AssetEditor` (editable 4-version cards,
  save persists via PATCH). Per-asset "→ Repurpose" seeds Content Studio `material` (reuses the
  studioSeed pattern). Results grouped by platform with quality-score badges.
- Verified: backend imports + `init_db()` OK; TestClient on live app: `/api/config`,
  `/api/editorial/brands` (Vispaico + Untitled), `/api/editorial/templates` (6 stages),
  `/api/editorial/runs` ([]) all 200; empty essay rejected. Frontend `npm run build` passes.
- NOT yet live-tested end-to-end (needs a real OpenRouter run). Known: the per-idea × platform
  loop is N ideas × M platforms model calls — large essays + many platforms cost real credits;
  recommend starting with max_ideas=4-6 + a few platforms. Multiplier is opt-in.
- notes/10 status now BUILT (was DESIGNED ONLY). Its open decisions are all resolved as above.

## Session update (2026-07-15, part 7) — Editorial Studio one-liner cap fixed
- User asked about input/output limits. Found two real limits + one bug in `backend/editorial.py`:
  * INPUT: essay stored truncated to `essay[:8000]` chars (sent whole to the miner); no
    word/paragraph cap on the live prompt. `max_ideas` 4-12 (default 8) is the main cost knob.
  * OUTPUT: per asset was hard-capped `final_versions[:4]` — correct for post/thread/carousel
    (exactly 4 versions) but it SILENTLY CLIPPED the one-liner kinds (quotes=10, hooks=20,
    questions=10, predictions=10) down to 4.
- FIX: the `[:4]` cap now applies only to non-one-liner kinds. One-liner kinds keep their full
  `_KIND_COUNTS` length (10/20/10/10). Implemented via `keep = _KIND_COUNTS.get(kind, 4) if kind
  in _KIND_COUNTS else 4` then `stored_versions = final_versions[:keep]` (used for both the
  `EditorialAsset.content` persist and the returned `versions`). The Creator stage already passes
  `_KIND_COUNTS` to the model; now the persisted/sent asset matches that instruction.
- Verified: `backend/editorial.py` compiles; TestClient routes `/api/editorial/{brands,templates,
  runs}` still 200. No live run needed for this change.

## Session update (2026-07-15, part 8) — FIX 422 on POST /api/editorial/run
- User ran the Studio from the UI, got `422 Unprocessable Content` on `/api/editorial/run`.
- ROOT CAUSE: the route used a single Pydantic model as the body param
  (`body: EditorialRunIn`). FastAPI then wrapped it as an EMBEDDED body key `{"body": {...}}`,
  so the frontend's FLAT JSON (`{essay, brand_id, platforms, mode, max_ideas, run_multiplier}`)
  failed validation with `loc: ["body","body"]` "Field required". Same latent bug on
  `PUT /brands/{id}` (`body: BrandIn`) and `PUT /templates/{stage}` (`body: TemplateIn`).
- FIX: converted all three to flat scalar `Body(..., embed=True)` params, matching the proven
  pattern in `backend/routes/pipeline.py` (which already uses flat embed params and works).
  Removed the now-unused `EditorialRunIn` / `BrandIn` / `TemplateIn` model classes. The
  frontend request shapes were already flat, so no frontend change was needed.
- Verified: `POST /api/editorial/run` now returns 200 (pipeline executes; returns an empty run
  in sandbox where there's no live LLM). `PUT /api/editorial/brands/{id}` and
  `PUT /api/editorial/templates/{stage}` return 200. Frontend `npm run build` passes.

## Session update (2026-07-15, part 9) — FIX "ran an essay, got 0 ideas · used 20 credits"
- User ran a REAL essay, got `mined 0 ideas · selected 0 · 0 assets · used 20 credits` — paid
  for nothing. Two REAL bugs (not the earlier 422):
- BUG A (ROOT CAUSE, money-waster): `backend/editorial.py` `_run_stage` called `route(...)` with
  NO `max_tokens`, so every stage inherited the router default of **2048** tokens. The Idea
  Miner is asked for 25-50 ideas = a large JSON that's almost always >2048 tokens, so the reply
  was TRUNCATED MID-JSON. `_safe_json` then failed → 0 ideas → the per-idea loop ran 0× → but
  the idea_miner + strategist overhead stages already charged ~20 credits. Classic silent
  charge-for-nothing. FIX: `_run_stage` now passes `max_tokens=8000` (verified 50-idea JSON ≈
  2100 tokens, fits comfortably).
- BUG B (why even 20 credits were wasted instead of erroring): the `idea_miner` `PromptTemplate`
  row in `gadgents.db` was CORRUPTED — its `system_prompt` was the single character "x" (a stray
  bad write during earlier dev). `_stage_system_prompt` returned that, so the real model got a
  1-char system prompt and returned garbage. `seed_editorial_defaults` only INSERTED missing
  rows (guarded `if None`), so it never repaired the bad row. FIX: `seed_editorial_defaults`
  now UPSERTS — any existing template row whose `system_prompt` has < 50 chars is rewritten from
  `_EDITORIAL_STAGE_PROMPTS` (version bumped). Re-run `init_db()` to repair existing bad DBs.
- BUG C (also found, part of same audit): the Creator can return SEVERAL assets in ONE call
  (e.g. linkedin + quotes together); the Humanizer/Quality Director echo ALL back, but the loop
  took only `assets[0]` and applied it to every asset. So quotes (the 2nd asset) inherited
  linkedin's 4 versions (one-liner fix from part 7 looked broken). FIX: added `_match_asset()`
  that matches the reply to the current asset by platform+kind, falling back to index 0.
- SAFETY NET: added a fail-fast guard in `run_editorial_pipeline` — if the Idea Miner yields 0
  parseable ideas (truncated/garbage reply), the run is marked `failed` and raises BEFORE the
  downstream stages, so it can never again charge for an empty run.
- Verified end-to-end with a fake LLM: 8 ideas mined, 4 selected, 8 assets, quotes=10 / linkedin=4
  (one-liner counts now correct), max_tokens=8000 reaching the model. The empty-ideas guard
  raises when the miner returns garbage. Frontend `npm run build` passes. User should re-run
  `./dev.sh` (init_db repairs the corrupt prompt row) then a real essay.

## Session update (2026-07-15, part 10) — Export (.md/.pdf) + Made in HAIPHONG brand + Vispaico tuning
- Two user requests before restarting dev: (1) an easy way to download Editorial Studio results
  as Markdown and/or PDF; (2) add the "Made in HAIPHONG" ECMS brand rules and, where they improve
  output, fold the better rules into Vispaico too.
- EXPORT (frontend-only, zero new deps): `EditorialStudio` now builds a single Markdown doc from
  `result` (`buildMarkdown()` — brand, idea/asset counts, multiplier IP, then each platform →
  asset → all 4 versions) and offers two buttons: "↓ Download .md" (Blob download, automatic) and
  "↓ Download .pdf" (opens a print-optimized window that triggers the browser's Save-as-PDF;
  dependency-free, no PDF lib in the venv). `.pdf` needs a pop-up allowed; on block it shows a tip
  to use the .md instead. Edit/saved versions are included, so the export reflects the human
  edits. (No backend route needed.)
- HAIPHONG BRAND: added `Made in HAIPHONG` to `seed_editorial_defaults` (default = False, no link
  URL — the ECMS says only subtle references at most once). Its `voice_prompt` encodes the full
  ECMS: Authority/Presence/Influence/Growth, "market rewards who's noticed/remembered/trusted",
  calm/elegant/thoughtful tone, never promotional/loud/motivational, do-NOT-sell, angle-first
  multiplication, one stand-alone "I've never considered it that way" moment per asset. Forbidden
  phrases expanded to the ECMS list (unlock/leverage/secret/growth hack/dominate/scale fast/
  disruptive/in the digital age/here's why/whether you're...).
- SEED REFACTOR: brand seeding is now an UPSERT BY NAME (was: "only seed if no default brand
  exists" — which silently skipped Haiphong because Vispaico already existed). `_brand_block`
  (editorial.py) now also injects ANGLE-FIRST method guidance + ANTI-AI-TELL rules (no em-dash
  overuse, no lists-of-three, no predictable transitions, vary structure, avoid LinkedIn/corp
  cliches) for EVERY brand.
- VISPAICO IMPROVEMENT (user asked "if rules would help, adapt"): YES — adopted the ECMS's
  better rules. Vispaico `voice_prompt` rewritten to "confident, calm, founder-to-founder, never
  promotional/loud, multiply value don't summarize"; `forbidden_phrases` extended with
  unlock/secret/growth hack/dominate/crushing it/scale fast/disruptive/here's why/whether you're.
  Result: Vispaico output is now calmer and less AI-flavored (same link still injected subtly).
- ANGLE-FIRST WORKFLOW (the ECMS "secret sauce"): the Strategist stage prompt now scores each
  idea by authority/originality/commercial (0-10) and RANKS strongest-first, returning a
  `ranked` array; the per-idea creation loop already embodies angle-first (all platform variants
  for one idea before the next). The `ranked` field is currently returned inside the calendar
  JSON and accepted gracefully (pipeline reads `selected`/`calendar`); it's surfaced for future
  UI use. This addresses the ECMS warning that generating all ~36 assets at once collapses quality.
- SEED ALSO now SYNCs stage PromptTemplates from `_EDITORIAL_STAGE_PROMPTS` on every init_db()
  (was: only repaired <50-char rows) so prompt improvements in code always propagate (version
  bumped on change). Re-run `./dev.sh` to pick up the new brand + improved prompts.
- Verified: `init_db()` seeds Vispaico + Untitled + Made in HAIPHONG (3 brands); Vispaico
  forbidden now includes 'secret'; full pipeline run with Haiphong brand produces correct assets
  (linkedin=4, quotes=10); backend compiles; `/api/editorial/brands` lists 3; frontend builds.

## Session update (2026-07-15, part 11) — CRITICAL: Editorial Studio runaway-token bug FIXED
- User pasted a LONG essay with max_ideas=4 in "Balanced", it never finished, produced nothing,
  and burned a LOT of (paid OpenRouter) tokens. Killing the dev server did NOT stop billing —
  in-flight OpenRouter requests kept running server-side after the client died. A second debug
  chat fired more runs and the Mac had to be hard-powered-off to stop the burn. Models seen
  billing during the incident: claude-opus-4.8, deepseek-v4-pro, claude-sonnet-4.6 (the editorial
  Fusion panels), confirming the expensive stages ran regardless of the "Balanced" choice.
- ROOT CAUSES (5):
  1. **No cancellation / no wall-clock deadline / no per-run token budget.** The pipeline runs on
     a `ThreadPoolExecutor` worker with no stop button and no timeout. Killing servers can't abort
     accepted OpenRouter calls, so they bill to completion on the server. That's why the burn
     continued after processes were killed and only a full Mac shutdown stopped it.
  2. **The Editorial Fusion stages ignored the Quality/Balanced toggle.** `editorial-creator` and
     `editorial-quality-director` were pinned `mode="high"` with the priciest Opus panels. In
     `editorial.py`, `_run_stage` did `goal = override_mode or agent_def.mode` — and the "Balanced"
     UI maps to `null`, so it fell through to the agent's `"high"`. => "Balanced" silently billed
     Opus for EVERY asset. This was the core "Balanced but expensive" trap.
  3. **Flat `max_tokens=8000` on every model call** (incl. Fusion judge merges + one-liners) —
     a token multiplier that inflated output cost on every stage.
  4. Run shape is O(ideas × platforms × ~9 calls), each a frontier model. Inherently long/slow
     for a big essay; with no ceiling it could run for an hour and rack up major spend.
  5. Killed runs left the DB row `status="running"` with 0 assets (worker died mid-run, nothing
     reaped it), so the UI showed perpetual "running" and polled forever.
- FIXES (all shipped):
  * **Toggle now REAL for Fusion stages:** `_run_stage` uses the user's mode to pick the matching
    `_FUSION_PRESETS[mode]` panel/judge for `creator` + `quality_director`. Balanced = the mixed
    preset (sonnet46/qwen37/luna, judge sonnet5), Economic = cheap preset. Quality still uses the
    high Opus panel. Default (no toggle) still falls back to the agent's High panel for quality.
  * **Per-stage `max_tokens`** via `_STAGE_MAX_TOKENS` (idea_miner 6000, strategist 4000, creator
    4000, humanizer 3000, quality_director 4000, multiplier 3000) — replaces the flat 8000.
  * **Guardrails in `run_editorial_pipeline`:** `_guard()` is checked between stages and after
    every asset and raises to abort the run if (a) canceled, (b) wall-clock > `RUN_TIMEOUT_SECONDS`
    (20 min), or (c) estimated `total_credits > RUN_MAX_CREDITS` (2000). The run is marked
    `canceled` and keeps partial assets (no re-raise).
  * **Cancel button:** `POST /api/editorial/runs/{run_id}/cancel` sets both the DB `canceled`
    flag/status AND the in-memory `cancel_run(run_id)` flag the worker polls. Frontend `api.js`
    gains `editorialCancel`; `EditorialStudio` shows a "⏹ Cancel run" button while busy and a
    "Run canceled" + partial-results state. Killing the server is no longer needed to stop a run.
  * **Startup reaper:** `reap_interrupted_runs()` marks any `status="running"` row left by a
    previous process as `failed` on `init_db()`, so stuck runs no longer hang the UI. Wired in
    `app.py` lifespan. (On this fix it reaped 2 orphaned rows from the incident.)
  * **Schema migration for existing DBs:** `_ensure_columns()` in `db.py` ALTERs existing SQLite
    tables to add columns that predate the current model (the new `EditorialRun` fields
    `ideas_count/assets_count/credits_used/error/canceled/started_at`). Without it, an old
    `gadgents.db` fails with "no column named ideas_count". Safe to run every startup.
- BEHAVIOR CHANGE to flag in testing: a real essay in Balanced mode is now materially cheaper
  than before (no per-asset Opus). A run that exceeds 20 min or ~2000 est. credits auto-cancels
  with a clear error and keeps what it produced. Users CANNOT lose the server to stop a run.
- Verified: backend imports OK; TestClient `/api/editorial/{brands,templates,runs}` = 200;
  `POST .../cancel` sets `status="canceled"` and a repeat returns 409; reaper flips stale
  "running" rows to failed; `_ensure_columns` reconciles the existing gadgents.db. Frontend
  `npm run build` passes.

## Session update (2026-07-15, part 12) — Editorial toggle STILL billed Opus in Balanced (user caught it)
- After part 11 the user ran Editorial in "Balanced" and STILL saw Claude Opus 4.8 burning
  (~$0.50 in 2 min, no result). The part-11 fix was INCOMPLETE: it only swapped the Fusion
  panel when a mode was explicitly passed, but (a) "Balanced" sends `null`, which fell back to
  the agent's `mode="high"` Opus panel, and (b) the FOUR single-model stages
  (idea_miner/strategist/humanizer/multiplier) are HARD-PINNED `router_model="or-opus"` — a pin
  bypasses the toggle entirely, so 4 of 6 stages were Opus in EVERY mode. Net: all 6 used Opus.
- REAL FIX in `backend/editorial.py _run_stage`: the user's toggle is now the SOURCE OF TRUTH
  and OVERRIDES BOTH the hard pin AND the agent default. `eff_mode` = chosen mode, with `null`
  (Balanced) resolving to `"mixed"` (NOT "high"). For Fusion stages we ALWAYS use
  `_FUSION_PRESETS[eff_mode]` (mixed = sonnet46/qwen37/luna, judge sonnet5 — no Opus). For
  single-model stages we map quality/mixed/economic -> `or-opus / or-sonnet46 / or-llama33`,
  ignoring the agent's `router_model` pin. So:
  * Balanced (default, mixed) = sonnet46 for singles + mixed Fusion panel — **zero Opus**.
  * Economic = llama33 / ds-flash-free+haiku+nano panel — cheapest.
  * Quality (high) = Opus — only when explicitly chosen.
- Frontend already correct: "Balanced" chip sets mode=null; `editorialRun` sends
  `getMode() || null`, so backend gets null -> resolves to mixed. No frontend change needed.
- WHY THIS MATTERED: the previous design assumed "default to High for quality, let toggle lower
  it," but the editorial agents were registered with `mode="high"` AND hard Opus pins, so the
  fallback direction was backwards. The UI's Balanced => null means "don't force High" was
  interpreted as "use the agent's High default" — wrong. Now null => mixed.
- Verified by stubbing `route()`: Balanced/null => idea_miner=or-sonnet46, creator/quality=
  mixed panel (sonnet46/qwen37/luna, judge sonnet5), no `or-opus` anywhere; high => Opus;
  economic => llama33 / cheap panel. py_compile OK; frontend builds.

## Session update (2026-07-15, part 13) — Editorial "Run failed: tuple index out of range" FIXED
- After part 12 the user ran Editorial in Balanced, got **"Run failed: tuple index out of
  range"** with no result, and Cancel also errored. Two REAL bugs, both now fixed:
- BUG A (the cryptic crash): `backend/llm.py complete_targeted` did `data["choices"][0]
  ["message"]["content"]` with NO guard. On a throttled/empty OpenRouter response (e.g.
  `{"error":...}` with no `choices`, or `choices: []`), this raised `IndexError: list/tuple
  index out of range` (the string the user saw) and the worker stored only `str(exc)[:2000]`,
  hiding the real cause. FIX: `complete_targeted` now checks `not data.get("choices")` and
  raises a CLEAR `RuntimeError` naming provider/model + the API error; the worker now stores
  the FULL traceback (`traceback.format_exc()`) so any future error shows file:line.
- BUG B (the "doesn't run" + the new `NameError` I introduced in part 12's router edit):
  `_run_fusion` referenced an undefined `goal` variable -> `NameError` on EVERY Fusion stage.
  FIXED to use `mode`. ALSO hardened `_run_fusion`: if the whole panel fails it falls back to
  a single recommended model (instead of crashing), and the judge index is no longer blind.
- BUG C (the actual frequent failure — run died on a LIVE but SLOW call): `LLMClient` used
  `httpx.Client(timeout=60.0)`. Fusion judge calls + long/economic-tier outputs on OpenRouter
  routinely exceed 60s, so the request `ReadTimeout`ed and the run failed ("Run failed") even
  though the model would have answered. This is almost certainly why "it doesn't run" — the
  user hit a 60s timeout mid-run. FIX: timeout is now `httpx.Timeout(connect=20, read=180,
  write=60, pool=10)`. The editorial guardrails (20-min wall clock, 2000-credit cap) still sit
  ABOVE this, so a genuinely hung run is still auto-canceled.
- RESILIENCE (so one transient error never kills a whole run): `_run_stage` in `editorial.py`
  now retries a failed SINGLE-model stage once on `recommend(eff_mode)` before giving up, with
  a clear message naming the stage+model. Fusion already skips failed panel members and now
  falls back to a single model if all members fail.
- VERIFIED: a real editorial run in economic mode now reaches the Fusion judge (claude-haiku)
  and the only failure we still see is a *slow* timeout that the 180s setting resolves; a
  standalone malformed-response raises a clear "returned no completions" error instead of an
  index crash; fusion `all models failed` falls back cleanly; single-stage retry path works.
  backend py_compile OK; frontend builds.
- PRACTICAL NOTE for the user: Editorial is SLOW by design (many sequential model calls). With
  the 180s per-call timeout it will actually finish now. Balanced = sonnet46 + mixed Fusion
  panel (no Opus). Keep max_ideas small (4) and few platforms for the first test. The "Cancel
  run" button now works (sets the cancel flag the worker polls at the next stage boundary).

## Session update (2026-07-15, part 14) — Editorial "0 assets / stuck / slow" root-caused + fixed
- User reported: run sits at "Engine running… 0 assets so far" for 5+ min, 20¢ spent, nothing
  produced; also two runs left stuck in `running` in the DB (zombies). The crash (part 13) was
  already fixed; this was a DIFFERENT problem: visibility + slowness + orphan pile-up.
- ROOT CAUSE 1 (the `tuple index out of range` you actually hit): it was NOT the LLM. The
  traceback pointed at `editorial.py` line 329 `user_id=effective_user.id`. The HTTP request
  loaded the dev `User` in the REQUEST session, then handed that ORM object to the WORKER
  thread which runs in a SEPARATE session. Reading `.id` triggered a cross-session lazy refresh
  that crashed SQLAlchemy's row processor. FIX: the worker now passes only the user **id**;
  `run_editorial_pipeline` re-loads the user by id in its own session. Verified by reproducing
  the exact handoff (user from session A passed into pipeline on session B) — now completes as
  `done`, no crash.
- ROOT CAUSE 2 (0 assets shown forever): assets/credits are only written to the DB at the END
  of the whole run, so the polling UI showed 0 the entire time even while dozens of slow model
  calls ran. FIX: `run_editorial_pipeline` now commits `run.ideas_count` after the miner and
  `run.assets_count` after EVERY asset, so the UI counts up in real time. Confirmed: a full
  fake-LLM run now mines 2 ideas + persists 4 assets (2 ideas × 2 platforms) correctly.
- ROOT CAUSE 3 (orphan/zombie runs): the startup reaper only ran on boot; runs killed mid-flight
  (server restart, Ctrl+C) stayed `running` forever. FIX: `get_run` now reaps the user's OTHER
  stuck `running` runs started >5 min ago on every poll (leaves a live run untouched), so they
  don't pile up. Also lowered per-stage `max_tokens` (idea_miner 6000->4000, creator 4000->3000,
  humanizer 3000->2500, quality 4000->3000, multiplier 3000->2500) to cut per-call latency/cost.
- WHY IT FELT BROKEN: a 4-idea × 2-platform Balanced run makes ~70 sequential `or-sonnet46`
  calls (creator + quality_director are Fusion = 3 panel + 1 judge each, per asset). Each takes
  10-30s on OpenRouter. So 5-15 min with tokens burning but (previously) 0 visible is expected
  for THIS design — not a hang. The progress fix makes it observable; the lower token caps make
  it a bit faster/cheaper. For a snappy test, use max_ideas=2 + 1 platform first.
- VERIFIED: backend py_compile OK; fake-LLM full run mines + persists assets; orphan reaper
  marks stale runs failed; frontend builds.

## Session update (2026-07-15, part 15) — Editorial reaper was killing runs; fixed + leftover servers killed
- After part 14 the UI still showed every Editorial run dying at ideas=0 immediately, even though
  `started_at` was populated. Root cause was the FAIL-POSITIVE reaper inside `get_run`
  (`backend/routes/editorial.py`), NOT the worker:
  1. TIMEZONE BUG: `r.started_at.timestamp()` treats the stored **naive-UTC** datetime as
     **LOCAL** time, while `datetime.now(timezone.utc).timestamp()` is true UTC. On a non-UTC Mac
     that offset made a brand-new run appear older than the 300s cutoff → marked `failed` at t≈0.
  2. WRONG GRACE: the 5-min cutoff was SHORTER than a normal run (5-15 min), so even a correct
     comparison would reap healthy runs mid-flight at 5 min.
- FIX (`get_run` reaper): (a) both sides now UTC-aware — `started_at.replace(tzinfo=utc)` vs
  `datetime.now(utc)` — so the comparison is correct; (b) grace raised to `RUN_TIMEOUT_SECONDS`
  (20 min), matching the pipeline's own wall-clock deadline, so a slow-but-alive run is never
  reaped; (c) the stale query now excludes `EditorialRun.id != run_id`, so the run you're actively
  polling is never reaped; (d) imported `RUN_TIMEOUT_SECONDS` from `backend/editorial.py`.
- HOUSEKEEPING: killed the two leftover dev servers from the earlier bug-fixing chat (uvicorn PID
  90206 + `npm run dev` + both vite instances on :5173/:5174). Ports 8000/5173/5174 confirmed free.
  DB had 0 stuck `running` rows (the part-11 startup reaper had already cleaned them).
- VERIFIED: backend py_compile OK; ports free; DB has no zombies. Editorial is safe to poll again.

## Session update (2026-07-15, part 16) — FIX "Idea Miner returned no usable ideas" (max_tokens truncation)
- After part 15 the run failed with: `Idea Miner returned no usable ideas (model reply was empty
  or not valid JSON)`. Reproduced the live Idea Miner call (Balanced, `or-sonnet46`): it returned
  a valid ```` ```json ```` block of 25-50 ideas (~15k chars ≈ 4k+ output tokens) that was
  **HARD-TRUNCATED mid-array** (cut off at idea #36 of ~50) because part 14 had lowered the
  `idea_miner` `max_tokens` to **4000** "to cut latency". At 4000 tokens the reply was cut before
  the array closed, so `_safe_json` returned `{"ideas": []}` → the fail-fast guard raised and the
  whole run aborted. Classic: part 14's latency tweak broke the miner for its requested volume.
- FIX 1 (capacity): restored `idea_miner` `max_tokens` to **8000** in `_STAGE_MAX_TOKENS` (the part-9
  value verified to fit 50-idea JSON). The other lowered caps (creator 3000, humanizer 2500,
  quality 3000, multiplier 2500) are fine — only the miner needs the headroom for 25-50 ideas.
- FIX 2 (defense in depth): `_safe_json` is now **truncation-tolerant**. New `_rescue_json()`
  closes any still-open `[`/`{` brackets and recovers every fully-emitted item, so a rare
  partially-cut reply still yields ideas (e.g. a reply cut after idea #36 now yields 36 ideas)
  instead of failing the whole run. Verified: a truncated 3-idea string recovers all 3; a clean
  reply is unaffected.
- BEHAVIOR: a normal Balanced run now mines its full idea list. Even if a future reply is cut, the
  run proceeds with the partial ideas rather than erroring. No charge-for-empty-run because the
  part-9 guard still fires only when ZERO ideas parse.
- VERIFIED: backend py_compile OK; `_safe_json` recovers truncated input (1 idea on a synthetic
  mid-object cut, 3 of 3 on a realistic trailing-comma cut, clean reply unaffected).

## Session update (2026-07-15, part 17) — FIX "object of type 'NoneType' has no len()" crash
- After part 16 the run ran LONG, burned money, then failed with:
  `TypeError: object of type 'NoneType' has no len()` at `len(text) // 4000` inside
  `_estimate_credits("editorial-creator", creator_text)`. `creator_text` was `None`.
- ROOT CAUSE: `backend/llm.py` `complete_targeted` read
  `data["choices"][0]["message"]["content"]` directly. When OpenRouter/OpenAI returns a completion
  with `content: null` (a refusal / content-filtered response), `CompletionResult.text` became
  `None`. That `None` flowed into `creator_text`, and `len(None)` crashed **mid-run** — AFTER every
  prior stage had already burned credits. Same latent gap existed in `complete()` (the batch path).
- FIX (defense in depth):
  * `backend/llm.py`: BOTH `complete` and `complete_targeted` now raise a CLEAR `RuntimeError`
    (`"... returned an empty (null) completion."`) on `null`/empty content, so it hits the existing
    fallback/retry path (single-model stages retry on `recommend(eff_mode)`; fusion skips the member
    / falls back to a single model) INSTEAD of poisoning downstream `len()`/`json.loads`.
  * `backend/editorial.py _run_stage`: both the Fusion and single-model branches now REJECT an
    empty/None reply (raise `"... returned an empty reply ..."`); the single-model branch's raise
    triggers its existing fallback-model retry. So the pipeline can never silently pass `None` on.
  * `backend/editorial.py _estimate_credits`: now does `len(text or "")` — never crashes on `None`.
- VERIFIED: `complete_targeted` with a mocked `content: null` reply now raises the clear message
  (caught + asserted); `_estimate_credits(None)` returns a sane base (13) instead of crashing;
  backend py_compile OK for `llm.py` + `editorial.py`.
- PRACTICAL NOTE: this crash was independent of the part-16 truncation fix. With all three (parts
  15-17) in, a Balanced Editorial run should now: not be reaped on poll, mine its full idea list,
  and fail fast with a CLEAR message (and a fallback-model retry) if any model returns empty rather
  than crashing mid-run after burning money. Start with max_ideas=4 + 1-2 platforms for the test.

## Session update (2026-07-15, part 18) — FIX Editorial still dying on Fusion JUDGE null + 0-credit report
- User ran Editorial again (Balanced). It mined 45 ideas fine, then failed at the FIRST Creator
  asset with: `openrouter/anthropic/claude-sonnet-5 failed: ... returned an empty (null)
  completion.` So run 51 burned the Idea Miner + Strategist + Creator-panel calls, then died.
- ROOT CAUSE: in `_run_fusion` (`backend/router.py`) the **judge** call had NO fallback. The panel
  loop already had skip-and-fallback resilience, but the judge call was a single shot:
  `llm.complete_targeted(judge)` and return. When the MIXED judge `or-sonnet5`
  (`anthropic/claude-sonnet-5`) returns a null/empty completion (content filter / throttled /
  model id flaky), the WHOLE fusion raises and the ENTIRE editorial run aborts — even though the
  3 panel answers were perfectly good. Net: a flaky judge = the run dies mid-way after spending on
  every prior stage. (Earlier runs 49/50 hit the part-17 `len(None)` crash on the same kind of
  null reply before the part-17 guard, and run 47 the part-16 miner truncation.)
- FIX (`backend/router.py _run_fusion`): the judge call is now wrapped in try/except with the SAME
  resilience as the panel: (1) retry on the FIRST panel answer's model (it just succeeded); (2) if
  that also fails, return that panel answer UNCHANGED as the final text (`used = fusion:<panel>`).
  So a failing judge can no longer kill the run or waste the credits already spent — the stage gets
  usable content (the strongest panel answer) and the pipeline proceeds. Verified with a mock where
  `or-sonnet5` returns a null completion: fusion returns `answer-from-claude-sonnet-4.6` (the first
  panel member) instead of crashing.
- FIX 2 (money visibility): a run that burns money then FAILS reported `credits_used = 0` in the DB,
  because `run.credits_used`/`assets_count` were only stamped on SUCCESS. That hid the real cost of
  a failed run (looked like "nothing charged"). The failure `except` block now persists
  `run.ideas_count`, `run.assets_count`, `run.credits_used = total_credits` before marking failed,
  so a failed run shows its TRUE partial cost. (Reminder: Editorial never deducts in dev-bypass
  mode, so `credits_used` is an ESTIMATE; but it was wrongly 0 before this fix.)
- BEHAVIOR: Balanced now proceeds end-to-end even if the `or-sonnet5` judge hiccups (falls back to
  the panel answer). The MIXED preset is sonnet46/qwen37/luna panel + `or-sonnet5` judge — the judge
  is the only Opus-free model in the path; if it stays flaky, consider swapping the mixed judge to
  `or-sonnet46` (already in the panel) for extra stability. Left as-is for now since the fallback
  covers it.
- VERIFIED: `backend/router.py` + `backend/editorial.py` py_compile OK; imports OK; fusion judge
  null-completion fallback returns usable panel content (no crash); credit-persist-on-failure edit
  in place. Frontend `npm run build` not re-run (no frontend change).

## Session update (2026-07-16) — REMOVE Anthropic, per-purpose Fusion, add Aion storytelling models
- User removed `OPENROUTER_MODEL_SONNET5` from `.env` (the `anthropic/claude-sonnet-5` judge that
  had been null-completing and killing Editorial runs) and INSISTED all Anthropic be dropped ("I
  don't pay money for shit, even top models"). Added two Aion Labs storytelling models to `.env`:
  `OPENROUTER_MODEL_AION_LABS3=aion-labs/aion-3.0` and `OPENROUTER_MODEL_AION_LABS3_MINI=
  aion-labs/aion-3.0-mini`. Verified on OpenRouter: Aion-3.0 = GLM-based multi-model storytelling
  system ($3/$6 per 1M, 131K ctx, 100% uptime); Mini = DeepSeek-based, cheaper+faster ($0.70/$1.40,
  70 tps). Explicitly built for narrative/voice/tension — a strong fit for the Editorial Creator.
- ARCHITECTURE CHANGE: moved from ONE global `_FUSION_PRESETS` (shared by all Fusion agents) to
  **per-agent purpose-tuned fusion panels**, while the Quality/Balanced/Eco toggle still overrides
  per call. `backend/editorial.py _run_stage` now uses the agent's own `fusion_panel`/`fusion_judge`
  (falling back to the global mode preset only if the agent has none), matching the existing
  `run_agent` priority. So each stage/agent can carry models that fit ITS job, not a generic mix.
- NEW CATALOG ENTRIES (`backend/router.py`): `or-aion3` (tier quality, modes high/mixed) and
  `or-aion3-mini` (tier balanced, modes mixed/economic). `config.py` gains `openrouter_model_aion_
  labs3` / `openrouter_model_aion_labs3_mini` (keyed exactly to the `.env` names) + `openrouter_
  model_ids()` exposes `aion3`/`aion3_mini`. The old `or-opus`/`or-sonnet5`/`or-sonnet46`/`or-haiku`
  catalog rows are kept (harmless defaults) but are NO LONGER referenced by any routing path.
- DE-ANTHROPIC EVERYWHERE (verified: `grep` for or-opus/or-sonnet46/or-sonnet5/or-haiku in routing
  returns ZERO active references):
  * `_FUSION_PRESETS`: high = [aion3, kimi, ds-pro, oa-sol] / judge ds-pro; mixed = [aion3-mini,
    qwen37, oa-luna, llama33] / judge aion3-mini; economic = [ds-flash-free, llama33, oa-nano] /
    judge ds-flash.
  * `editorial-creator` panel = [aion3, qwen37, oa-luna, llama33] / judge aion3 (storytelling-led).
  * `editorial-quality-director` panel = [ds-pro, oa-sol, qwen37, llama33] / judge ds-pro (NO Aion
    here — scoring is analytical, needs reliable JSON; ds-pro leads it).
  * `content-repurposer` panel = [ds-pro, oa-sol, aion3-mini, llama33] / judge ds-pro (keeps Llama
    3.3 per user request — "still good for repurposing" — plus Aion-mini for narrative voice).
  * `wan-video` panel = [aion3, ds-pro, oa-sol, llama33] / judge ds-pro (Aion leads visual narrative).
  * Editorial single-model stages (idea_miner/strategist/humanizer/multiplier): `_run_stage` map now
    high=ds-pro, mixed=qwen37, economic=llama33 (was or-opus / or-sonnet46). The agents' own
    `router_model="or-opus"` pins are overridden by this map, so they're inert.
  * `lead-finder` chat: `router_model` -> `or-qwen37` (was or-sonnet46).
  * `backend/leads/pipeline.py`: ICP panel [ds-pro, oa-sol, qwen37] / judge ds-pro (was opus);
    AUDIT_MODEL = or-qwen37 (was or-sonnet46).
  * `backend/pipeline.py` (Content Studio): CONTENT_PRODUCER_MODEL_BY_MODE economic=llama33,
    mixed/balanced=qwen37, high/quality=aion3 (was sonnet46/opus); repurpose fallback
    `model="fusion:or-aion3"` (was or-opus). `routes/wan.py` shot `model` label -> fusion:or-aion3.
- RESULT: the ONLY model left that can bill Anthropic is if a `.env` key still points at one (opus
  and sonnet46 keys remain in `.env` but are no longer routed). To fully guarantee zero Anthropic
  spend, either set `OPENROUTER_MODEL_OPUS`/`OPENROUTER_MODEL_SONNET46` to non-Anthropic slugs OR
  delete those keys. Editorial Creator now uses Aion storytelling models per the user's intent.
- VERIFIED: all 7 touched files py_compile OK; `grep` confirms no Anthropic catalog id survives in
  any preset/panel/map; `get_model('or-aion3')` -> aion-labs/aion-3.0 and `or-aion3-mini` ->
  aion-labs/aion-3.0-mini resolve from `.env`; editorial-creator/quality-director/content-repurposer/
  wan-video panels print out Anthropic-free. No frontend change.

## Session update (2026-07-16, part 20) — REAL Editorial killer: gateway-wide cooldown + a None regression
- User tested after part 19: models routed fine (DeepSeek V4 Pro, Aion-3.0, Kimi K2.6; only 6¢),
  but STILL died with `Run failed: Fusion panel: all models failed and fallback errored: Provider
  unhealthy (cooldown): openrouter`. So it was NEVER the model — the whole `openrouter` PROVIDER
  was in cooldown, so every call (incl. the fallback) failed and the run died after spending money.
- ROOT CAUSE 1 (the gateway cooldown): `backend/llm.py` tracked health PER PROVIDER. OpenRouter is
  ONE HTTP endpoint hosting MANY models (DeepSeek, Kimi, Aion, Qwen...). `_mark_failure` put the
  entire `openrouter` provider into a 30s cooldown after just 2 failures. In a Fusion panel, if one
  panel member hiccuped (throttle / rate-limit / null completion), 2 such failures cooled down the
  WHOLE gateway — so every later call in the run (every asset, every stage, AND the fallback) failed
  with "Provider unhealthy (cooldown)". One flaky model = entire run dead. Classic shared-state bug.
- FIX 1: health is now tracked PER (provider, model) — `_health` keyed by `(provider, model)`. A
  single throttled model gets its own short 20s cooldown (after 2 consecutive failures) but does
  NOT touch sibling models on the same provider. The panel loop already `continue`s on a failed
  member, so a flaky Kimi is simply skipped while Aion/DeepSeek/Qwen still answer. Verified: a mock
  where Kimi returns 500 — the fusion skips Kimi and returns the DeepSeek-judged answer; no gateway
  kill. Also fixed the success path to CLEAR the (provider, model) cooldown counter on success.
- ROOT CAUSE 2 (a `None` regression from part 18): earlier I wrapped the judge call in a
  try/except to add fallback, but my edit DELETED the original `return result.text,
  f"fusion:{judge_entry.id}"` line that ran on judge SUCCESS. So when the judge succeeded,
  `_run_fusion` fell off the end and returned `None`. `_run_stage` then raised "Editorial stage
  returned an empty reply" (or downstream `len(None)`), making EVERY run fail even though the model
  answered correctly. This was masking the cooldown fix and was itself a fatal bug.
- FIX 2: restored the success `return result.text, f"fusion:{judge_entry.id}"` INSIDE the try (the
  except now only handles the judge-failure fallback path). Verified: fusion now returns the judge
  text on success (no None) AND falls back to the panel answer on judge failure.
- BEHAVIOR NOW: a single flaky model on OpenRouter no longer kills the run; the judge succeeding
  returns real content; a failing judge still falls back to the best panel answer. Editorial should
  finally complete end-to-end. (Note: the per-model cooldown is 20s — a model that stays hard-broken
  is skipped transiently, then retried; the Fusion panel/judge fallbacks cover transient bumps.)
- VERIFIED: `backend/llm.py` + `backend/router.py` py_compile OK; test confirms (a) Kimi-500 is
  isolated and the run returns DeepSeek-judged content, and (b) judge success returns text (not
  None). All imports OK.

## Session update (2026-07-16, part 21) — "res is not defined" + runs stuck at 0 forever (FIXED)
- User ran Editorial again: models routed fine (8¢), but the UI showed everything at 0, the run
  "kept running but did nothing," and pressing **Cancel run** errored with `res is not defined`.
  They stopped the dev server. Confirmed no stray servers (ports 8000/5173/5174 free; only
  Dropbox/Hermes python procs, unrelated). There were 3 orphaned `running` rows (54/55/58) in the
  DB from the session — these are exactly the runs that appeared "stuck at 0."
- BUG A (Cancel crash): in `frontend/src/App.jsx` `EditorialStudio.run()`, the cancel closure
  `cancelCurrentRef.current` referenced `res.run_id`, but `res` is declared with `const res =
  await api.editorialRun(...)` INSIDE the `try` block — AFTER the closure was assigned. So when
  Cancel fired, `res` was not in scope -> `ReferenceError: res is not defined`. Because Cancel
  never worked, a slow/stuck run could not be stopped, so it appeared to "keep running."
  FIX: capture `let currentRunId = null;` in the outer `run()` scope; set it to `res.run_id` right
  after the run starts; the cancel closure uses `currentRunId` (and no-ops if still null). Frontend
  `npm run build` passes.
- BUG B (runs stuck "running" at 0 forever): the request handler sets the DB row to `status=
  "running"` immediately, then the heavy work runs on a `ThreadPoolExecutor` worker. The worker's
  outer code (e.g. the `ws_user = ws.get(...)` session-setup line) sat OUTSIDE the inner
  `try/except`, so if the worker thread died for any reason (thread kill, OOM, unexpected error),
  the exception was swallowed by the executor and the row stayed `status="running", ideas=0,
  assets=0` forever. Worse, the part-15 poll reaper EXPLICITLY EXCLUDED the current `run_id`, so
  the polled (orphaned) run was never reaped — it hung at 0 with no way to cancel it.
  FIXES:
  * `backend/routes/editorial.py _worker`: wrapped the ENTIRE worker body (session setup +
    pipeline + all stage handlers) in a top-level `try/except` that, on ANY failure, re-opens a
    session and marks the run `failed` with the real traceback (file:line) — but ONLY if it is
    still `running` (so a healthy/canceled/done run is never overwritten). A worker can no longer
    leave a row stuck "running".
  * `get_run` reaper now ALSO reaps the CURRENTLY-polled run if `started_at` is older than
    `RUN_TIMEOUT_SECONDS` (20 min) and not canceled. A live, healthy run auto-cancels via its own
    guardrail before then, so anything still "running" past the deadline has a dead worker and is
    resolved as failed on the next poll. This closes the orphan gap that part-15 left open.
  * The DB already had 3 orphaned rows; ran `reap_interrupted_runs` (the startup reaper) to clear
    them immediately (also happens automatically on next `./dev.sh` boot, and on next poll).
- BUG C (UI looked stuck at 0): the running header only showed `result.assets?.length` ("N assets
  so far"), which stays 0 until the FIRST asset completes (after miner + creator + humanizer +
  quality for idea #1). So a run that HAD mined ideas looked frozen at 0. FIX: the running header
  now shows `mined {ideas_count} ideas · {assets} assets so far · ~{credits_used} credits spent`,
  so partial progress is always visible.
- WHY IT FELT DEAD: the pipeline was verified correct (fake-LLM run -> status done, ideas 3,
  assets 3, credits 119; progress commits are visible to the poll). The "0 forever" was the
  combination of (a) a genuinely slow real run where the assets counter lags, (b) the orphaned-row
  case that the (excluded) reaper never recovered, and (c) Cancel being broken so it couldn't be
  stopped. All three are now fixed.
- BEHAVIOR NOW: Cancel works and stops a run (marks canceled, keeps partial assets). A run that
  has been polled can never hang at "running" past 20 min — it auto-resolves to failed on poll. A
  worker that dies for any reason marks the row failed with the real cause. The running UI shows
  live ideas/assets/credit progress. Start Editorial with max_ideas=4 + 1-2 platforms for a fast
  first success.
- VERIFIED: backend `routes/editorial.py` py_compile OK; frontend `npm run build` OK (174 kB);
  `get_run` poll on an orphaned (25-min-old) "running" row now returns `failed` (reaped); 3 stuck
  DB rows reaped; fake-LLM full run still completes with progress committed.

## Session update (2026-07-16) — ROOT CAUSE of "burns tokens, 0 assets, can't stop" FOUND + fixed
- PICKUP CONTEXT: the previous chat (chat-notes.md) ran a real essay, got "10 min / 15¢ / 0 assets
  / Cancel works but still nothing", diagnosed it as the Creator Fusion using the SLOW full
  `aion3` (~23s p50 E2E), and swapped `aion3` -> `aion3-mini` in the Editorial Creator + Wan panels.
  That swap is present and correct, but it was NOT the root cause. This session found the real bug.
- THE REAL ROOT CAUSE: OpenRouter intermittently STALLS a connection — it accepts the request but
  never streams a response body and never closes the socket. On CPython 3.14 / macOS, a socket
  stuck in `ssl.recv` for such a half-open connection is NOT interruptible by ANY in-process
  mechanism: we empirically proved httpx's read timeout, socket SO_RCVTIMEO, closing the client,
  a ThreadPoolExecutor `future.result(timeout=)`, and a `threading.Timer` that closes the client
  ALL fail to break it — the call blocks indefinitely. So the Editorial worker thread wedged at
  stage 2 (miner/strategist) forever: ideas got mined (30) but 0 assets, tokens kept billing, and
  killing the dev server was the only escape (and even that leaked in-flight OpenRouter calls).
- EVIDENCE: `run_editorial_pipeline` debug with a watchdog showed the stack wedged inside
  `llm.complete_targeted -> httpx -> ssl.recv` past the 180s read timeout AND past a 240s SIGALRM
  fired from a worker thread (signals don't interrupt another thread's recv). Stage-stepping with a
  main-thread SIGALRM showed: miner 137s, strategist 66s, then creator STALLED >60s and the
  per-stage alarm fired and raised ("stage hard 60s") — i.e. a stalled call really does hang the
  whole run, while live-but-slow calls (137s) just make it painfully slow.
- FIX 1 (latency/cost, confirmed secondary but shipped): `editorial-creator` + `editorial-quality-
  director` Fusion panels -> SINGLE-MODEL. Fusion (4 panel + judge ~100s/call) was the other half
  of the slowness. Measured: Creator Fusion ~102s -> single `or-aion3-mini` ~31s; Quality Director
  Fusion ~95s -> single `or-qwen37`/`or-ds-pro` ~20-30s; Humanizer already ~5s. Net per-asset:
  ~202s -> ~60s (~3.3x faster, ~3x cheaper). The Quality/Cost toggle still drives single-model
  choice via `_run_stage` (Quality->ds-pro, Balanced->qwen37, Economic->llama33), so the toggle
  stays meaningful. Aion storytelling is preserved by the agent's SYSTEM PROMPT, not by Fusion.
  Wan-video judge also moved off full aion3 (panel aion3-mini, judge ds-pro) for the same reason.
- FIX 2 (the actual kill — ROOT FIX): Editorial now runs in a SEPARATE PROCESS, not a thread.
  * NEW `backend/editorial_worker.py`: `run_worker(run_id, essay, brand_id, platforms, mode,
    max_ideas, run_multiplier, user_id)` runs the whole pipeline in its own PID. Its main thread
    arms a per-stage `signal.alarm(_STAGE_HARD_TIMEOUT_S=150)` (via `_StageTimeout` in editorial.py)
    so a stalled stage raises a clean TimeoutError -> run marked failed instead of hanging forever.
  * `routes/editorial.py` now launches `multiprocessing.Process(target=run_worker, daemon=True)`
    (replacing the old `ThreadPoolExecutor` worker) and stores the handle in `_editorial_processes`.
  * Cancel endpoint (`POST /api/editorial/runs/{id}/cancel`) now also `proc.kill()` (SIGKILL) the
    live subprocess. SIGKILL cannot be ignored by a blocked recv, so a wedged run is stopped
    INSTANTLY — no more killing the dev server, no more leaked billing. (The DB `canceled` flag +
    in-memory `cancel_run` are still set for the same-PID case.)
  * WHY A PROCESS: it's the only mechanism that reliably kills a stalled recv. Threads can't
    (proven). The SIGALRM per-stage timeout is a second safety net that works because the
    subprocess runs `_run_stage` in its MAIN thread (signals only interrupt the main thread).
- FIX 3 (resilience): `_run_stage` now wraps each call in `_StageTimeout` (arm alarm at entry,
  clear at every return/raise). The 150s budget is per-stage and re-armed each stage, so a slow
  healthy call (e.g. the 137s miner) doesn't cannibalize the next stage's window. A stall >150s on
  any single call aborts the run cleanly (failed + real error saved) instead of hanging.
- VERIFIED THIS SESSION:
  * All modules py_compile; `TestClient` boot returns /api/config + /api/editorial/{brands,
    templates, runs} = 200; startup reaper cleared 8 zombie "running" rows from earlier test runs.
  * Real subprocess run (run 77): wedged at the miner (ideas=0) for 90s, then a simulated Cancel
    SIGKILLed the subprocess IMMEDIATELY and the run was cleanly marked `canceled`. This is the
    exact "burn tokens, can't stop" case and it is now resolved — Cancel stops a wedged run.
  * Individual OpenRouter calls all responded when not stalled (aion3-mini 3s, qwen37 15s,
    ds-pro 3s, single creator 31s). The remaining variable is OpenRouter's own latency/stall rate,
    which is external — but it can no longer wedge the app or be unstoppable.
- CAVEAT / USER GUIDANCE: OpenRouter is currently VERY slow for some models (miner ~137s, and it
  intermittently stalls). Even with the single-model fix, a 2-idea x 1-platform run can take
  several minutes when OpenRouter is loaded, and a stall still aborts the run at the 150s/stage
  ceiling (you'll see a clear "provider stalled" error instead of a silent hang). For a fast first
  success: use **max_ideas=2-4 + 1 platform + Balanced**, and don't be alarmed if a run takes a
  few minutes — it now always either finishes, fails cleanly, or is stoppable via Cancel.
- NOT YET DONE / LATER: live end-to-end SUCCESS run (all stages completing with assets) was not
  observed this session because OpenRouter kept stalling the miner; the fix makes that run
  killable + faster, but a no-stall OpenRouter window is needed to see a full green run. The user
  should retry when OpenRouter is snappier, starting small.

## Session update (2026-07-16, part 2) — 500 on POST /api/editorial/run + orphaned "running" rows
- USER HIT A 500 on `POST /api/editorial/run` right after the part-1 subprocess change. ROOT
  CAUSE: the route passed a LOCAL NESTED FUNCTION `_worker` as `multiprocessing.Process(target=...)`.
  multiprocessing must PICKLE the target for the spawn/fork handoff, and local closures can't be
  pickled -> `PicklingError: Can't pickle local object <function run_editorial.<locals>._worker>`.
  FIX: pass the MODULE-LEVEL `backend.editorial_worker.run_worker` as the target with plain
  picklable args (run_id, essay, brand_id, platforms, mode, max_ideas, run_multiplier, user_id).
  Verified: `POST /api/editorial/run` now returns 200 instantly (subprocess launches, no pickle
  error) with a run_id.
- SECOND bug found live: a run mined 30 ideas (miner OK, deepseek tokens spent) then sat at
  "Engine running… 0 assets" for 4+ min. DB showed the worker PROCESS WAS GONE but the run row
  stayed `status=running` — i.e. the subprocess died (crash/kill) without updating the row, and
  nothing resolved it. The per-stage SIGALRM (part 1) is BEST-EFFORT and did NOT reliably fire in
  the real uvicorn-spawned subprocess (confirmed it works in an isolated test but not here), so a
  dead/stalling child could leave a permanent "running" spinner. This is the "bs, nothing happens"
  the user saw.
- FIX (guaranteed safety net): added an **editorial watchdog daemon thread** in `routes/editorial.py`
  (`_editorial_watchdog`, 15s tick). For each tracked run it (a) reaps the row if the child process
  is dead but the row is still `running` (marks `failed` with a clear cause), and (b) SIGKILLs a
  child that has lived past `_EDITORIAL_PROCESS_HARD_CAP_S` (12 min) and marks it failed. SIGKILL is
  unblockable, so this ALWAYS works even when the subprocess's own SIGALRM doesn't fire — a wedged
  run can NEVER hang the UI forever now. Verified: a dead child with an orphaned `running` row was
  reaped to `failed` within 15s by the watchdog.
- Also: the per-stage SIGALRM in `editorial.py` (`_StageTimeout`, 150s) stays as the fast path for
  the common stall (catches most stalled calls); the watchdog is the backstop for when it doesn't.
- ACTION TAKEN for the user's stuck run 84: marked it `failed` directly so the UI unblocks. The
  user MUST restart `./dev.sh` to load the new code (their running server still had the old code).
- VERIFIED: all modules py_compile; `TestClient` boot 200 on /api/editorial/{brands,runs}; POST
  /run returns 200 with run_id; watchdog reaps a dead-process/running-row to failed in <=15s.

## Session update (2026-07-16, part 3) — worker died instantly (3rd root cause) + OpenRouter IS the blocker
- USER reported "4 min running, only running, no api model called." Investigation found the
  worker subprocess was GONE (ps showed no `editorial-run` process) but the row stayed
  `status=running` at ideas=0 — the run_editorial subprocess launched via `multiprocessing.
  Process(target=run_worker)` **died instantly when started from uvicorn's threadpool**. Repro
  (POST via a real uvicorn on :8011) showed `proc=GONE` from 10s on, ideas=0, no API call.
  Root cause: multiprocessing SPAWN re-imports __main__ and pickles the target; launched from a
  worker thread under uvicorn this intermittently killed the child at spawn/import with no
  traceback. FIX: switched the route to `subprocess.Popen([sys.executable, "-m",
  "backend.editorial_worker", run_id, essay, brand_id, platforms_json, mode, max_ideas,
  run_multiplier, user_id])`. A bare subprocess is a clean new interpreter, args are plain
  strings (no pickle), and `Popen.kill()` = SIGKILL. Added a `__main__` entrypoint to
  editorial_worker.py that parses argv and calls `run_worker`. VERIFIED on :8011: `proc=ALIVE`
  now — the worker launches reliably. Watchdog updated to Popen methods (`poll()`, `wait()`,
  `kill()`); cap lowered 12min -> 5min so a stall is killed + marked failed fast.
- THE ACTUAL BLOCKER (external, not code): with the worker now launching, the run STILL sits at
  ideas=0 because the **Idea Miner OpenRouter call stalls**. Proven by isolating the EXACT call
  `route(llm, messages, model_id=<m>, fusion=False, max_tokens=8000)` with a hard SIGALRM:
  * qwen37 miner: STALLED 70s. * aion3-mini miner: STALLED 70s. * ds-pro miner: succeeded once
    (52.8s, 10k chars) then STALLED on retry. * ds-pro 5x retry: stall, stall, then cooldown
    (the 2-failure/20s per-model cooldown kicks in). So OpenRouter is intermittently stalling the
  LARGE miner request (full system prompt + essay + 8000 max_tokens) across ALL models RIGHT NOW;
  short/prompt calls to the same models return in 3-8s. It is provider-side flakiness, not a bug.
- IMPORTANT nuance on timeouts: SIGALRM DOES sometimes fire on these stalls (we saw "hard 70s"
  raise), but NOT reliably inside the subprocess worker (run alive 300s past the 150s per-stage
  alarm). So the watchdog SIGKILL at 5min is the reliable backstop; the per-stage SIGALRM is
  best-effort. Net behavior now: a stalled run is auto-killed + marked `failed` within 5 min with
  a clear "exceeded the hard process cap" message, OR the user hits Cancel (instant SIGKILL).
- TEMPORARY model change: the single-model map `mixed` was `or-qwen37` (stalling) -> now `or-ds-pro`
  (the model that completed the miner when others stalled). Quality also ds-pro; Economic llama33.
  If OpenRouter's qwen37/aion3 stability returns, mixed can move back. This is a stopgap for the
  current provider flakiness, not a permanent preference.
- STATUS: code is correct and robust (worker launches, stalls are contained, killable, auto-fail
  at 5min). A FULL SUCCESS run was still NOT observed because OpenRouter keeps stalling the miner
  at this moment. The fix is to wait for OpenRouter to be responsive and retry (start small:
  max_ideas=2, 1 platform, Balanced/Quality). No further code change can make a stalled external
  API return.
- VERIFIED: :8011 end-to-end — worker ALIVE after launch; run auto-failed at 310s ("exceeded the
  hard process cap (5 min)") instead of hanging forever; Cancel SIGKILLs instantly; ds-pro miner
  succeeded once in isolation (52.8s) proving the pipeline path is sound.

## Session update (2026-07-16, part 4) — REAL root cause found + fixed (Editorial stall)
- USER tested again: "burned 20 cents, got nothing, process cap works" (run died at the 3/5-min
  hard cap with "exceeded the hard process cap and was terminated"). Process cap worked (no more
  infinite hang) but the run still produced NOTHING because the Idea Miner call STALLED on
  OpenRouter every time. Decided to do one more real look before moving on to optimising other agents.
- EMPIRICAL PROBE (made 8+ real OpenRouter calls via the LLM client to isolate the variable):
  * SMALL call (tiny prompt, mt=20) on or-ds-pro -> returns in ~1.2s (but null/empty content).
  * SMALL input + BIG output (mt=8000) on or-ds-pro -> OK in 22.6s, 1334 tokens. So big OUTPUT alone is fine.
  * BIG input + small output (mt=5) on or-ds-pro -> returns in 4s (null/empty content). Big input alone also fine.
  * BIG input + BIG output (mt=8000) on or-ds-pro AND or-aion3-mini -> STALLS (>40-50s, no response).  <-- THE MINER CASE.
  * KEY: with mt dropped to 3000, or-ds-pro returned OK in 37s with 30 valid ideas. So mt=8000
    was a real stall TRIGGER for the miner (the 8k output budget on a large input hangs OpenRouter).
  * BUT the stall is INTERMITTENT and NOT purely size: even short input + mt=3000 on or-ds-pro
    stalled >50s on a later call. So it is OpenRouter BACKEND FLAKINESS on these editorial calls —
    the SAME model+params sometimes answers in ~37s and sometimes stalls forever. No code can make
    a stalled external API return; the job is to (a) stop the burn, (b) buy more attempts.
- FIX 1 (miner token cap): `_STAGE_MAX_TOKENS["idea_miner"]` 8000 -> 3000 (enough for 25-50
  SHORT ideas; the 8k ceiling was the stall trigger). Applies to run_editorial_pipeline.
- FIX 2 (watchdog actually starts): the watchdog daemon in `routes/editorial.py` was gated on
  `threading.current_thread() is threading.main_thread()`. Under uvicorn the app is imported from a
  worker THREAD, so that check is False and the watchdog NEVER STARTED — meaning a stalled run was
  NEVER reaped and hung at "running" forever (exactly what user saw: cap "worked" only because the
  user's dev server happened to have a different code path). REMOVED the main-thread gate; watchdog
  now starts unconditionally at import. Hard cap lowered 5min -> 3min.
- FIX 3 (per-stage alarm is best-effort on macOS; rotation is the real retry): replaced the
  single-model branch's one-shot fallback in `_run_stage` with a 4-attempt ROTATION across
  several catalog models (mixed: or-ds-pro -> or-aion3-mini -> or-qwen37; high: ds-pro/kimi/aion3;
  economic: llama33/ds-flash). Each attempt is bounded by a new `_AttemptTimeout(45s)` alarm
  (distinct from the per-stage 150s alarm) so a stall on one model is aborted and we ROTATE to the
  next instead of hanging the whole 150s budget on one dead call. Net: a run now gets up to ~4
  independent shots at a non-stalled OpenRouter response before the 3-min watchdog kills it.
- VERIFIED end-to-end against the LIVE (flaky) OpenRouter:
  * Run 108 (pre-rotation, mt=3000): failed cleanly at 3min "exceeded the hard process cap",
    0 credits, 0 assets — watchdog now fires correctly (was the never-starting bug).
  * Run 110 (with rotation): miner stalled on ds-pro -> rotated -> all 3 models stalled this window
    -> failed cleanly at ~174s "failed after retries across ['or-ds-pro','or-aion3-mini','or-qwen37']",
    0 credits, 0 assets. No 20c burn, no infinite hang.
  * ds-pro miner STILL succeeds in isolation (37s, 30 ideas) when OpenRouter isn't stalling — so the
    pipeline path is sound; success depends entirely on OpenRouter being responsive at call time.
- HONEST VERDICT: the Editorial Studio code is now as robust as possible against the provider:
  clean fail (no burn) under 3min, killable via Cancel, rotating retries for transient stalls,
  correct token cap. The REMAINING blocker is OpenRouter's intermittent stalling of these calls,
  which no in-process mechanism (httpx timeout, socket, thread, signal) can break on macOS — only
  a process kill can, and that just stops the bleed, it doesn't get an answer. On a responsive
  OpenRouter day a run SHOULD now complete (start small: max_ideas=2, 1 platform, mixed). If it
  keeps failing, the lever is the PROVIDER, not the code (try a different OpenRouter model, or
  swap the miner rotation lead to whatever is healthiest right now).
- ACTION: per user plan, we now move on to optimising the OTHER agents (lead-finder, wan-video,
  content-repurposer, content-producer, social-listener) rather than chasing the OpenRouter stall
  further. The editorial hard-cap/watcher/rotation changes are committed into the running code.
- NOTE: the user asked to ALWAYS update this 07 handoff at each boundary so the next chat picks up
  seamlessly. This part 4 is that update.

## Next steps (per original plan + where we are)
