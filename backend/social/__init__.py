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
        html = _wait_and_scrape(page, url, scroll=8)
        soup = BeautifulSoup(html, "html.parser")
        posts = []
        for article in soup.find_all("article"):
            text_el = article.find("div", {"data-testid": "tweetText"})
            if not text_el:
                # Skip shells (promoted/empty/quoted shells) that have no body text.
                continue
            text = text_el.get_text(" ", strip=True)
            if not text:
                continue
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
    """Scrape top LinkedIn posts for a topic. Returns normalized posts.

    We use LinkedIn's **search results / content** page (topic-scoped) rather than the
    home feed: the feed is the user's contacts' activity (e.g. "<You> liked this…") which
    is not about the enquiry, so it produced only notification/contact noise. The search
    page returns real posts that mention the topic. LinkedIn hides reach/impressions
    (author-only); we capture likes/reactions. Reaction counts appear as "N reactions"
    strings; we climb to the enclosing post card for the body + author.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import quote_plus

    browser = _build_browser()
    try:
        page = browser.new_page()
        url = f"https://www.linkedin.com/search/results/content/?keywords={quote_plus(topic)}"
        html = _wait_and_scrape(page, url, scroll=8)
        soup = BeautifulSoup(html, "html.parser")
        posts = []
        seen = set()
        # Drop notification / contact / "people you may know" cards (defensive — search
        # rarely returns these, but the feed did, so keep the guard).
        _NOISE = re.compile(
            r"liked (your|this)|reacted to (your|this)|commented on (your|this)|"
            r"reposted (your|this)|mentioned you|viewed your|followed you|"
            r"new notification|you have [0-9,]+ new|people you may know|"
            r"you might like|celebrated|shared a milestone|is hiring|"
            r"see who's hiring|turn on notifications|invited you|endorsed you|"
            r"wants to connect|sent you a (message|connection)|pending requests",
            re.I,
        )
        for el in soup.find_all(string=re.compile(r"^[0-9,]+[KMBkmb]?\s+reactions?$")):
            like = _parse_count(el.strip().split()[0])
            node = el.parent
            card = None
            for _ in range(12):
                if node is None:
                    break
                txt = node.get_text(" ", strip=True)
                if len(txt) > 120:
                    card = txt
                    break
                node = node.parent
            if not card:
                continue
            # Drop the "Feed post" header LinkedIn prepends and any promoted/suggested cards.
            card = re.sub(r"^Feed post\s*", "", card).strip()
            if "Promoted" in card[:60] or "Suggested" in card[:60]:
                continue
            if _NOISE.search(card):
                continue
            if card in seen:
                continue
            seen.add(card)
            # Author: the in-card /in/ link's visible text (up to "•"); else slug-derived.
            author = ""
            author_el = node.find("a", href=re.compile(r"/in/")) if node else None
            if author_el is not None:
                link_text = author_el.get_text(" ", strip=True)
                if link_text and "•" in link_text:
                    author = link_text.split("•")[0].strip()
                elif link_text:
                    author = link_text.split("  ")[0].strip()
                else:
                    slug = author_el.get("href", "").rstrip("/").split("/")[-1]
                    author = slug.replace("-", " ").title() if slug else ""
            if not author:
                head = card.split("•")[0].strip()
                author = head.split("  ")[0][:60] if head else ""
            posts.append(_normalize_post({
                "author": author, "text": card,
                "like_count": like, "repost_count": 0,
                "reply_count": 0, "url": "",
            }))
        ranked = sorted(posts, key=lambda x: x["like_count"], reverse=True)
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
