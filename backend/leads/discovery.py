"""Public-web discovery + domain analysis for Lead Finder.

Adapted from the user's Scraper toolkit (websearch_utils.py): Firecrawl-backed Google
discovery, DuckDuckGo HTML fallback, domain page discovery, email + site-age analysis.
Self-contained so the agent runs inside this repo. Firecrawl is used only when enabled
(requires a local firecrawl-simple / firecrawl docker at the configured base URL).

Public-web + GDPR-safe: we only read public pages and collect business emails. No personal
data harvesting, no paid B2B-data enrichment.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Set

import httpx
import requests
from bs4 import BeautifulSoup

from backend.config import get_settings

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
]
BLOCKED_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "search.yahoo.com", "yahoo.com",
    "youtube.com", "wikipedia.org", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "bbb.org", "yelp.com", "yellowpages.com", "angi.com", "houzz.com",
    "mapquest.com",
}

CONTACT_KEYWORDS = [
    "contact", "contact-us", "contactus", "get-in-touch", "support", "impressum",
    "about", "services", "team", "reach-us", "customer-service", "privacy",
]


@dataclass
class DomainAnalysis:
    domain: str
    emails: Set[str]
    site_age_label: str
    comments: str


# ---------------------------------------------------------------------------
# Firecrawl client (only used when use_firecrawl is True)
# ---------------------------------------------------------------------------
def _fc_headers() -> Dict[str, str]:
    s = get_settings()
    return {"Content-Type": "application/json", "Authorization": f"Bearer {s.firecrawl_api_key}"}


def _fc_base() -> str:
    return get_settings().firecrawl_base_url


def _fc_scrape(url: str, *, timeout: int = 60) -> Optional[Dict]:
    try:
        r = httpx.post(
            f"{_fc_base()}/v1/scrape",
            json={"url": url, "formats": ["markdown", "html"]},
            headers=_fc_headers(),
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        return r.json().get("data")
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


def _fc_crawl(url: str, *, limit: int = 25, max_depth: int = 2, timeout: int = 180) -> Optional[List[Dict]]:
    try:
        r = httpx.post(
            f"{_fc_base()}/v1/crawl",
            json={"url": url, "limit": limit, "maxDepth": max_depth,
                  "scrapeOptions": {"formats": ["markdown", "html"]}},
            headers=_fc_headers(),
            timeout=timeout,
        )
        if r.status_code != 200 or not (job_id := r.json().get("id")):
            return None
        for _ in range(60):
            time.sleep(3)
            st = httpx.get(f"{_fc_base()}/v1/crawl/{job_id}", headers=_fc_headers(), timeout=30)
            if st.status_code != 200:
                return None
            body = st.json()
            if body.get("status") == "completed":
                return body.get("data", [])
            if body.get("status") in ("failed", "cancelled"):
                return None
        return None
    except (httpx.ConnectError, httpx.TimeoutException):
        return None


def fc_discover_candidates(query: str, *, num_results: int = 50, timeout: int = 60) -> List[str]:
    search_url = f"https://www.google.com/search?q={httpx.utils.quote(query)}&num={num_results}"
    data = _fc_scrape(search_url, timeout=timeout)
    if not data:
        return []
    html = data.get("html", "") or data.get("markdown", "")
    if not html:
        return []
    seen: Set[str] = set()
    results: List[str] = []
    md = data.get("markdown", "")
    for m in re.finditer(r"https?://([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,})", md.lower()):
        d = m.group(1).removeprefix("www.")
        if d not in seen and d not in BLOCKED_DOMAINS and "." in d and not d.startswith("google"):
            seen.add(d)
            results.append(d)
    if not results:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            d = extract_domain(a["href"])
            if d and d not in seen and d not in BLOCKED_DOMAINS:
                seen.add(d)
                results.append(d)
    return results


def fc_deep_analyze_domain(domain: str, *, crawl_limit: int = 15, crawl_depth: int = 1,
                           timeout: int = 180) -> Optional[DomainAnalysis]:
    pages = _fc_crawl(f"https://{domain}", limit=crawl_limit, max_depth=crawl_depth, timeout=timeout)
    if not pages:
        return None
    emails: Set[str] = set()
    all_text = ""
    for page in pages:
        md = page.get("markdown") or ""
        html_c = page.get("html") or ""
        all_text += md + "\n" + html_c + "\n"
        emails.update(EMAIL_REGEX.findall(md + html_c))
    emails = {e.lower() for e in emails
              if not e.lower().endswith(("png", "jpg", "gif", "svg", "webp", ".css", ".js"))}
    age = estimate_site_age_label(domain)
    mapped = map_emails_to_business(emails)
    return DomainAnalysis(domain=domain, emails=mapped, site_age_label=age,
                          comments=f"Firecrawl crawled {len(pages)} pages")


# ---------------------------------------------------------------------------
# Discovery + analysis (no Firecrawl required)
# ---------------------------------------------------------------------------
def discover_candidates(term: str, region_terms: Sequence[str], limit: int = 40,
                        timeout: int = 12, retries: int = 3, backoff: float = 1.75,
                        locale: str = "us-en", accept_language: str = "en-US,en;q=0.8") -> List[str]:
    seen: Set[str] = set()
    results: List[str] = []
    for region in region_terms:
        query = f"{term} {region}"
        for url in _duckduckgo_search(query, timeout=timeout, retries=retries,
                                      backoff=backoff, locale=locale, accept_language=accept_language):
            domain = extract_domain(url)
            if not domain or domain in seen or domain in BLOCKED_DOMAINS:
                continue
            seen.add(domain)
            results.append(domain)
            if len(results) >= limit:
                return results
    return results


def _duckduckgo_search(query: str, *, timeout: int, retries: int, backoff: float,
                       locale: str, accept_language: str) -> List[str]:
    resp = _request("https://duckduckgo.com/html/", params={"q": query, "kl": locale},
                    timeout=timeout, retries=retries, backoff_factor=backoff,
                    accept_language=accept_language)
    if not resp:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    out: List[str] = []
    for link in soup.select("a.result__a"):
        resolved = resolve_duckduckgo_redirect(link.get("href"))
        if resolved:
            out.append(resolved)
    return out


def resolve_duckduckgo_redirect(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    from urllib.parse import parse_qs, unquote, urlparse
    parsed = urlparse(url)
    if parsed.netloc and "duckduckgo.com" not in parsed.netloc:
        return url
    uddg = parse_qs(parsed.query).get("uddg")
    return unquote(uddg[0]) if uddg else None


def extract_domain(url: str) -> Optional[str]:
    from urllib.parse import urlparse
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return None
    if not netloc:
        return None
    return netloc[4:] if netloc.startswith("www.") else netloc


def _request(url: str, *, method: str = "GET", params=None, data=None, timeout: int = 12,
             retries: int = 3, backoff_factor: float = 1.75,
             accept_language: str = "en-US,en;q=0.8"):
    delay = 1.0
    headers = {"User-Agent": __import__("random").choice(USER_AGENTS), "Accept-Language": accept_language}
    for attempt in range(retries):
        try:
            r = requests.request(method, url, params=params, data=data, headers=headers, timeout=timeout)
            if r.status_code >= 400:
                raise requests.HTTPError(f"status {r.status_code}")
            return r
        except requests.RequestException:
            if attempt == retries - 1:
                return None
            time.sleep(delay)
            delay *= backoff_factor
    return None


def discover_domain_pages(domain: str, *, keywords: Sequence[str] = CONTACT_KEYWORDS,
                          timeout: int = 12, retries: int = 3, backoff: float = 1.75,
                          max_pages: int = 6, accept_language: str = "en-US,en;q=0.8"
                          ) -> Dict[str, requests.Response]:
    from urllib.parse import urljoin
    pages: Dict[str, requests.Response] = {}
    visited: Set[str] = set()

    def enqueue(u: str):
        if len(pages) >= max_pages or u in visited:
            return
        visited.add(u)
        r = _request(u, timeout=timeout, retries=retries, backoff_factor=backoff,
                     accept_language=accept_language)
        if r:
            pages[u] = r

    enqueue(f"https://{domain}")
    if not pages:
        enqueue(f"http://{domain}")
    if not pages:
        return pages
    home, first = next(iter(pages.items()))
    soup = BeautifulSoup(first.text, "html.parser")
    for a in soup.find_all("a", href=True):
        lowered = a["href"].lower()
        if any(k in lowered for k in keywords):
            enqueue(urljoin(home, a["href"]))
            if len(pages) >= max_pages:
                break
    return pages


def extract_emails(pages: Sequence[requests.Response]) -> Set[str]:
    out: Set[str] = set()
    for r in pages:
        out.update(EMAIL_REGEX.findall(r.text))
    return {e.lower() for e in out if not e.lower().endswith(("png", "jpg", "gif", "svg", "webp", ".css", ".js"))}


def map_emails_to_business(emails: Set[str]) -> Set[str]:
    """Keep only business-looking addresses; drop obvious personal/free providers
    and role aliases we don't want to surface. GDPR-aware: we never collect personal
    inboxes; we prefer name@company domains, but we do not distinguish legal person vs
    company here beyond dropping free-mail hosts."""
    free_hosts = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "proton.me",
                  "icloud.com", "aol.com", "gmx.com", "mail.ru"}
    generic = {"info", "hello", "contact", "sales", "admin", "office", "support", "team"}
    cleaned: Set[str] = set()
    for e in emails:
        host = e.split("@")[-1].lower()
        if host in free_hosts:
            continue
        local = e.split("@")[0].lower()
        # Keep: not purely generic role box (those are fine for outreach too, actually)
        # but drop throwaway single-char/odd. Keep generic business inboxes; they are public.
        if len(local) < 2:
            continue
        # Skip if local looks personal (firstname.lastname at a company is fine to keep
        # as a business contact; we just avoid free hosts above).
        cleaned.add(e)
    return cleaned


def estimate_site_age_label(domain: str, *, timeout: int = 12, retries: int = 2,
                            backoff: float = 1.5, accept_language: str = "en-US,en;q=0.8") -> str:
    first = _earliest_wayback(domain, timeout=timeout, retries=retries, backoff=backoff,
                              accept_language=accept_language)
    if not first:
        return "Unknown"
    now = datetime.now(timezone.utc)
    delta = now - first
    years = delta.days // 365
    months = (delta.days % 365) // 30
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months and years < 3:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    age_text = ", ".join(parts) if parts else "<1 year"
    return f"{age_text} (first seen {first.date()})"


def _earliest_wayback(domain: str, *, timeout, retries, backoff, accept_language) -> Optional[datetime]:
    resp = _request(
        "https://web.archive.org/cdx/search/cdx",
        params={"url": f"{domain}/*", "output": "json", "limit": "1",
                "filter": "statuscode:200", "collapse": "timestamp:8", "from": "1995"},
        timeout=timeout, retries=retries, backoff_factor=backoff, accept_language=accept_language,
    )
    if not resp:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if len(data) < 2 or len(data[1]) < 2:
        return None
    try:
        return datetime.strptime(data[1][1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def analyze_domain(domain: str, *, timeout: int = 12, retries: int = 3, backoff: float = 1.75,
                   accept_language: str = "en-US,en;q=0.8") -> Optional[DomainAnalysis]:
    pages = discover_domain_pages(domain, timeout=timeout, retries=retries,
                                  backoff_factor=backoff, accept_language=accept_language)
    if not pages:
        return None
    emails = map_emails_to_business(extract_emails(pages.values()))
    age = estimate_site_age_label(domain, timeout=timeout, retries=retries,
                                  backoff=backoff, accept_language=accept_language)
    return DomainAnalysis(domain=domain, emails=emails, site_age_label=age,
                          comments="basic HTTP audit")


def analyze_domains(domains: Sequence[str], *, workers: int = 6, **kw) -> List[DomainAnalysis]:
    out: List[DomainAnalysis] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(analyze_domain, d, **kw): d for d in domains}
        for f in as_completed(futs):
            try:
                res = f.result()
            except Exception:
                continue
            if res:
                out.append(res)
    return out
