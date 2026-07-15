# Social Listener — setup note (agent #5)

Pulls posts from **X** and **LinkedIn** by topic via [CloakBrowser](https://github.com/CloakHQ/CloakBrowser)
(a stealth Chromium, drop-in Playwright replacement). The agent reuses a **logged-in browser
session** from a persistent profile, so it browses as you. Results are sorted by engagement
(likes / reposts / replies). A per-post **Repurpose** button sends the post text into Content Studio.

> Reach/impressions are NOT captured — that metric is author-only and never in another user's
> post DOM. We sort on likes/engagement only (per product decision).

## 1. Install CloakBrowser (optional dependency)
```bash
pip install cloakbrowser[geoip]
```
The backend imports it **lazily** (only when a listen actually runs), so the rest of the app
boots without it. macOS ships the free **v146** build; **v148+** needs a Pro license key.

## 2. Create a persistent logged-in profile
The listener sets `user_data_dir` to `SOCIAL_PROFILE_DIR`. You must pre-seed it with a real
logged-in session, otherwise X/LinkedIn will show a login wall (and scraping fails).

Easiest path — run the seeder (one-time, headed). It uses `launch_persistent_context`
(NOT `launch(user_data_dir=...)`, which is a TypeError in this version) and logs in manually:
```bash
source .venv/bin/activate
python seed_social_profile.py        # opens X + LinkedIn; log in by hand; prints Done
```
Keep that dir. Point `SOCIAL_PROFILE_DIR` at it. You can also copy an existing Chrome profile
directory instead of logging in fresh.

> IMPORTANT: use `wait_until="domcontentloaded"` (NOT `"networkidle"`) when navigating
> X/LinkedIn — they poll constantly and never reach network idle, so `networkidle` times out
> at 60s and the login/capture gets skipped. `backend/social/__init__.py` and the seeder both
> use `domcontentloaded` + a short settle for this reason.

## 3. Configure `.env`
```
SOCIAL_PROFILE_DIR=~/.cloakbrowser/social-profile
SOCIAL_PROXY=http://user:pass@host:port     # residential proxy, recommended to avoid IP bans
CLOAKBROWSER_LICENSE_KEY=                     # only for Pro v148+ builds
```
All three are read in `backend/social/__init__.py` via `get_settings()`. See `.env.example`
for the documented keys.

## 4. Run / verify
Launch both servers with `./dev.sh`, open Social Listen, enter a topic + platforms, hit Listen.
- Without a profile → a `[scrape failed: ...]` post appears (graceful, no crash).
- With a profile → posts return, sorted by likes desc; persisted under `/api/social/queries`.

## Notes / risks
- **ToS + ban risk:** reading another platform's posts through an authenticated session violates
  X/LinkedIn ToS. This is a deliberate, user-accepted product decision — not a code concern.
  A residential proxy + the persistent profile reduce (not eliminate) ban risk.
- LinkedIn is more aggressive at flagging automation even with stealth; treat it as
  likes-sort-with-caveat.
- Engagement parsing is DOM-driven and will drift when X/LinkedIn change their markup; the
  listeners are the place to patch (`listen_x` / `listen_linkedin`).

## Endpoints
- `POST /api/social/listen` {topic, platforms[], limit} → persists + returns posts
- `GET  /api/social/queries` → past listens
- `GET  /api/social/queries/{id}/posts` → posts for a query (sorted by likes)
