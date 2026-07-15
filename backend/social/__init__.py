"""Social Listener: scrape X / LinkedIn posts by topic via CloakBrowser.

CloakBrowser is a stealth Chromium (drop-in Playwright replacement). It drives a real,
undetected browser using a persistent logged-in profile. Posts are read from the rendered
DOM; engagement counts (likes/retweets/replies) are parsed for client-side sorting.

This module declares CloakBrowser as an OPTIONAL dependency: it's only imported when a
listen job actually runs, so the rest of the app boots fine without it installed.
"""

from __future__ import annotations

import re
from typing import Optional

from backend.config import get_settings

_NUM_RE = re.compile(r"([\d.]+)\s*([KMBkmb]?)?")


def _parse_count(text: str) -> int:
    """Parse '1.2K' / '3.4M' style counts into ints."""
    if not text:
        return 0
    m = _NUM_RE.search(text.replace(",", ""))
    if not m:
        return 0
    val = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(val * mult)


def _build_browser():
    """Lazily import + launch CloakBrowser (persistent profile) with our configured
    profile/proxy/humanize. Returns a BrowserContext (use ctx.new_page())."""
    try:
        from cloakbrowser import launch_persistent_context
    except ImportError as exc:  # pragma: no cover - dependency optional
        raise RuntimeError(
            "CloakBrowser is not installed. Run: pip install cloakbrowser[geoip]"
        ) from exc

    s = get_settings()
    kwargs = {
        "headless": True,
        "humanize": True,
    }
    # Persistent profile so the logged-in X / LinkedIn session is reused.
    if s.social_profile_dir:
        kwargs["user_data_dir"] = s.social_profile_dir
    if s.social_proxy:
        kwargs["proxy"] = s.social_proxy
        kwargs["geoip"] = True
    if s.cloakbrowser_license_key:
        kwargs["license_key"] = s.cloakbrowser_license_key
    return launch_persistent_context(**kwargs)


def _wait_and_scrape(page, url: str, scroll: int = 5) -> str:
    # X / LinkedIn never reach "networkidle" (constant polling); use domcontentloaded
    # plus a fixed settle, then scroll to trigger lazy-loaded posts.
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    for _ in range(scroll):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(800)
    return page.content()


def _normalize_post(raw: dict) -> dict:
    return {
        "author": raw.get("author", ""),
        "text": raw.get("text", ""),
        "like_count": raw.get("like_count", 0),
        "repost_count": raw.get("repost_count", 0),
        "reply_count": raw.get("reply_count", 0),
        "url": raw.get("url", ""),
    }


def listen_x(topic: str, limit: int = 20) -> list[dict]:
    """Scrape top X posts for a topic (hashtag or keyword). Returns normalized posts."""
    from bs4 import BeautifulSoup

    browser = _build_browser()  # persistent context (see _build_browser)
    try:
        page = browser.new_page()
        url = f"https://x.com/search?q={_quote(topic)}&f=top"
        html = _wait_and_scrape(page, url)
        soup = BeautifulSoup(html, "html.parser")
        posts = []
        for article in soup.find_all("article")[: limit * 2]:
            text_el = article.find("div", {"data-testid": "tweetText"})
            if not text_el:
                continue
            text = text_el.get_text(" ", strip=True)
            author = ""
            user_link = article.find("a", href=re.compile(r"^/[^/]+$"))
            if user_link:
                author = user_link.get("href", "").strip("/")
            # X exposes engagement in a single aria-label, e.g.
            # "49 replies, 222 reposts, 1827 likes, 4722 bookmarks, 357078 views"
            like = reply = repost = 0
            for el in article.find_all(attrs={"aria-label": re.compile(r"like|repl", re.I)}):
                label = el.get("aria-label", "")
                for kind, key in (("replies", "reply"), ("reposts", "repost"), ("likes", "like")):
                    m = re.search(rf"([\d.]+[KMBkmb]?)\s*{kind}", label, re.I)
                    if m:
                        val = _parse_count(m.group(1))
                        if kind == "replies":
                            reply = max(reply, val)
                        elif kind == "reposts":
                            repost = max(repost, val)
                        else:
                            like = max(like, val)
            status_link = article.find("a", href=re.compile(r"/status/\d+$"))
            post_url = "https://x.com" + status_link["href"] if status_link else ""
            posts.append(_normalize_post({
                "author": author, "text": text,
                "like_count": like, "repost_count": repost,
                "reply_count": reply, "url": post_url,
            }))
            if len(posts) >= limit:
                break
        return posts
    finally:
        browser.close()


def listen_linkedin(topic: str, limit: int = 20) -> list[dict]:
    """Scrape top LinkedIn posts. Returns normalized posts.

    LinkedIn hides reach/impressions (author-only); we capture likes/reactions at best.
    The search-results page lazy-loads empty under headless, so we scrape the FEED
    (already populated) and filter by topic keywords in the post text. Reaction counts
    appear as "N reactions" strings; we climb to the enclosing post card for text.
    """
    from bs4 import BeautifulSoup

    browser = _build_browser()
    try:
        page = browser.new_page()
        # Feed is reliably rendered; search results are not under stealth headless.
        html = _wait_and_scrape(page, "https://www.linkedin.com/feed/")
        soup = BeautifulSoup(html, "html.parser")
        posts = []
        seen_texts = set()
        topic_l = topic.lower()
        # Anchor on reaction-count strings, then climb to the post card.
        for el in soup.find_all(string=re.compile(r"^[0-9,]+[KMBkmb]?\s+reactions?$")):
            like = _parse_count(el.strip().split()[0])
            node = el.parent
            card = None
            for _ in range(10):
                if node is None:
                    break
                txt = node.get_text(" ", strip=True)
                if len(txt) > 120:
                    card = txt
                    break
                node = node.parent
            if not card:
                continue
            # Drop "Feed post" header noise and promoted/suggested cards.
            card = re.sub(r"^Feed post\s*", "", card).strip()
            if "Promoted" in card[:60] or "Suggested" in card[:60]:
                continue
            if card in seen_texts:
                continue
            seen_texts.add(card)
            author_el = node.find("a", href=re.compile(r"/in/")) if node else None
            author = ""
            if author_el is not None:
                # Prefer the link's visible text up to "•"; else derive from the /in/ slug.
                link_text = author_el.get_text(" ", strip=True)
                if link_text and "•" in link_text:
                    author = link_text.split("•")[0].strip()
                elif link_text:
                    author = link_text.split("  ")[0].strip()
                else:
                    slug = author_el.get("href", "").rstrip("/").split("/")[-1]
                    author = slug.replace("-", " ").title() if slug else ""
            if not author:
                # Fallback: feed card text often starts with "<Author> • <time>".
                head = card.split("•")[0].strip()
                author = head.split("  ")[0][:60] if head else ""
            # Topic match is a SOFT preference (LinkedIn headless feed isn't topic-scoped):
            # keep topic hits first, but always keep top-reaction posts as a fallback.
            is_match = topic_l in card.lower()
            posts.append(_normalize_post({
                "author": author, "text": card,
                "like_count": like, "repost_count": 0,
                "reply_count": 0, "url": "",
                "_match": is_match,
            }))
        # Prefer topic matches; if too few, top up with highest-reaction posts.
        matches = sorted([p for p in posts if p.pop("_match", False)], key=lambda x: x["like_count"], reverse=True)
        others = sorted([p for p in posts if not p.pop("_match", False)], key=lambda x: x["like_count"], reverse=True)
        ranked = matches + others
        return ranked[:limit]
    finally:
        browser.close()


def _quote(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(s)


# Map platform id -> listener fn.
_LISTENERS = {
    "x": listen_x,
    "linkedin": listen_linkedin,
}


def listen(platforms: list[str], topic: str, limit: int = 20) -> list[dict]:
    """Run the chosen platform listeners and return merged, platform-tagged posts."""
    out: list[dict] = []
    for p in platforms:
        fn = _LISTENERS.get(p)
        if not fn:
            continue
        try:
            for post in fn(topic, limit):
                post["platform"] = p
                out.append(post)
        except Exception as exc:  # surface as a single failed post so the UI can warn
            out.append({
                "platform": p, "author": "", "text": f"[scrape failed: {exc}]",
                "like_count": 0, "repost_count": 0, "reply_count": 0, "url": "",
            })
    # Sort by likes desc so the most engaging posts surface first.
    out.sort(key=lambda x: x.get("like_count", 0), reverse=True)
    return out
