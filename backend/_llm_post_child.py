"""Child entrypoint for backend._llm_post (run as `python -m backend._llm_post_child`).

Reads ONE JSON request {url, headers, json} from stdin, POSTs it, and prints
ONE JSON result line to stdout: {"ok": true, "status": N, "data": ...} on
success, or {"ok": false, "error": "..."} on failure. The parent
(backend._llm_post.timed_post) reads that line with a wall-clock deadline and
SIGKILLs this process if it stalls -- the only reliable kill for a half-open
OpenRouter recv on macOS.
"""

import json
import sys

import httpx


def main() -> None:
    try:
        req = json.loads(sys.stdin.read())
        client = httpx.Client(
            timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=10.0)
        )
        resp = client.post(req["url"], headers=req.get("headers", {}), json=req["json"])
        client.close()
        try:
            data = resp.json()
        except Exception:
            data = {"_status": resp.status_code, "_text": resp.text[:2000]}
        sys.stdout.write(json.dumps({"ok": True, "status": resp.status_code, "data": data}))
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
