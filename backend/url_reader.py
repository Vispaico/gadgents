"""Read the text content of one or more URLs for the Content Studio.

Reuses the existing web-fetch building blocks from the leads toolkit so we don't
maintain a second fetch path:
  - Firecrawl (if configured & reachable): richer markdown via backend.leads.discovery._fc_scrape
  - Fallback: plain HTTP GET + BeautifulSoup (public articles/pages)
If Firecrawl is unavailable the fallback is used automatically. Content is trimmed to a
sane cap so it fits in the prompt. Public-web only; GDPR-safe (we just read text).
"""

from __future__ import annotations

import re
from typing import List

from backend.config import get_settings

# Cap per URL and total so we don't blow up the prompt context.
_MAX_CHARS_PER_URL = 12000
_MAX_CHARS_TOTAL = 40000


def _firecrawl_available() -> bool:
    s = get_settings()
    url = getattr(s, "firecrawl_base_url", None)
    return bool(url)


def _read_one_firecrawl(url: str) -> str | None:
    try:
        from backend.leads.discovery import _fc_scrape
    except Exception:
        return None
    data = _fc_scrape(url, timeout=60)
    if not data:
        return None
    md = data.get("markdown") or ""
    if md:
        return md.strip()
    return None


def _read_one_http(url: str) -> str | None:
    try:
        from backend.leads.discovery import _request
        from bs4 import BeautifulSoup
    except Exception:
        return None
    resp = _request(url, timeout=15, retries=2, backoff_factor=1.5)
    if not resp:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def read_urls(urls: List[str]) -> str:
    """Return concatenated readable text from URLs, or an empty string if none read."""
    blocks: List[str] = []
    total = 0
    for url in urls:
        url = (url or "").strip()
        if not url:
            continue
        if not re.match(r"^https?://", url):
            url = "https://" + url
        text: str | None = None
        if _firecrawl_available():
            text = _read_one_firecrawl(url)
        if not text:
            text = _read_one_http(url)
        if not text:
            continue
        text = text[:_MAX_CHARS_PER_URL]
        blocks.append(f"--- SOURCE: {url} ---\n{text}")
        total += len(text)
        if total >= _MAX_CHARS_TOTAL:
            break
    return "\n\n".join(blocks)
