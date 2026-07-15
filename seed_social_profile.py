"""One-time profile seeder for the Social Listener agent.

Opens X and LinkedIn in a HEADED CloakBrowser window using a persistent profile dir so you
can log in manually ONCE. After you close this script, the saved session is reused by every
`/api/social/listen` call (no more login needed).

Usage:
    source .venv/bin/activate
    python seed_social_profile.py

Then set in .env:
    SOCIAL_PROFILE_DIR=/Users/<you>/.cloakbrowser/social-profile
"""

from pathlib import Path

from cloakbrowser import launch_persistent_context

PROFILE_DIR = str(Path.home() / ".cloakbrowser" / "social-profile")

# Persistent context so the logged-in session is SAVED to PROFILE_DIR and reused by
# every /api/social/listen call. Headed + humanize so YOU can type credentials.
ctx = launch_persistent_context(
    PROFILE_DIR,
    headless=False,
    humanize=True,
)

print(f"Profile dir: {PROFILE_DIR}")
print("A browser will open. Log into X and LinkedIn manually, then CLOSE the window.")
print("(Leave this terminal running until you're done logging in.)")

pages = [
    "https://x.com/login",
    "https://www.linkedin.com/login",
]

for url in pages:
    try:
        page = ctx.new_page()
        # domcontentloaded (not networkidle — X/LinkedIn never go idle) + settle.
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        input(f"-- Log in to {url} in the browser, then press ENTER here when done: ")
        page.close()
    except Exception as e:  # noqa: BLE001
        print(f"Could not open {url}: {e}")

print("Closing context and saving profile…")
ctx.close()
print("Done. Profile saved. Now set SOCIAL_PROFILE_DIR in .env and restart the backend.")
