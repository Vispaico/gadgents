# Social Listener — how to re-login (when X / LinkedIn log you out)

The Social Listener reuses a **persistent CloakBrowser profile** at
`SOCIAL_PROFILE_DIR` (`/Users/n3ils/.cloakbrowser/social-profile`). That profile holds your
logged-in X + LinkedIn sessions (cookies). It survives restarts, but:

- X may force re-auth after days/weeks, or if it detects a new IP (hence the proxy).
- LinkedIn may log you out similarly.
- If you ever clear the profile dir, you must log in again from scratch.

When a listen returns **0 posts** or the posts look like a **login wall**, re-seed the session.
This note is the exact, copy-paste procedure.

---

## When do I need to re-login?
Quick check from a terminal (no backend needed):
```bash
cd /Users/n3ils/Sites/gadgents
source .venv/bin/activate
python - <<'PY'
from cloakbrowser import launch_persistent_context
ctx = launch_persistent_context('/Users/n3ils/.cloakbrowser/social-profile', headless=True, humanize=True)
p = ctx.new_page()
p.goto('https://x.com/home', wait_until='domcontentloaded', timeout=60000); p.wait_for_timeout(5000)
print('X logged in:', 'Log in' not in p.content())
p.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=60000); p.wait_for_timeout(5000)
print('LinkedIn logged in:', 'Sign in' not in p.content() and 'Join now' not in p.content())
ctx.close()
PY
```
If either prints `False`, re-login that platform.

---

## Re-login procedure (full, headed)

1. **Open a terminal** (Terminal.app / iTerm) and go to the project:
   ```bash
   cd /Users/n3ils/Sites/gadgents
   ```

2. **Activate the Python venv** (the CloakBrowser install lives here — NOT system Python):
   ```bash
   source .venv/bin/activate
   ```
   Your prompt should now show `(.venv)`. If you skip this, `cloakbrowser` won't be found.

3. **Run the seeder** (it opens a real browser window):
   ```bash
   python seed_social_profile.py
   ```
   - A headed CloakBrowser window opens.
   - For **X**: log in. If X sends an email/2FA code, complete it in the browser. The session
     cookie is what gets saved, not the code.
   - Back in the terminal, press **ENTER** when done with X.
   - For **LinkedIn**: log in the same way, then press **ENTER**.
   - It prints `Done. Profile saved.` and the window closes.

4. **No backend restart needed** — the profile is read from disk on every listen. But if the
   backend (`uvicorn`) is currently running, you can leave it; the next listen picks up the new
   session.

> Why `launch_persistent_context` and not `launch`? CloakBrowser stores the session in
> `user_data_dir` only via `launch_persistent_context(...)`. Using `launch(user_data_dir=...)`
> is a TypeError (this is already handled in `seed_social_profile.py` and `backend/social/__init.py`).

> Navigation uses `wait_until="domcontentloaded"` (NOT `networkidle`). X/LinkedIn poll forever
> and never reach "network idle"; `networkidle` times out at 60s and skips the capture.

---

## Optional: re-login only ONE platform
The seeder always opens both. If you only need to refresh X, that's fine — logging in X and
pressing ENTER, then just closing the LinkedIn step (Ctrl-C the terminal, or log in too), still
saves the whole profile. To re-seed just one platform cleanly, edit `pages` in
`seed_social_profile.py` to keep only that URL, run it, then revert.

---

## Proxy (recommended, reduces ban risk)
Without a proxy, every listen comes from your home IP. Add a **residential proxy** to `.env`:
```
SOCIAL_PROXY=http://user:pass@host:port
```
Format is a standard proxy URL (http/https or `socks5://user:pass@host:port`). After editing
`.env`, restart the backend so `get_settings()` reloads it. CloakBrowser then routes through that
IP and sets `geoip=True` (timezone/locale match the proxy). Get a proxy from Bright Data,
Oxylabs, Smartproxy, etc. Leave `SOCIAL_PROXY=` empty to run without one (fine for light use).

---

## Verify after re-login
Re-run the check at the top of this note — both lines should print `True`. Then in the app:
`./dev.sh`, open **Social Listen**, enter a topic, pick platforms, **Listen**. You should get
real posts with engagement counts.
