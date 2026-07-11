"""Lead Finder orchestrator chain (agent #3).

Stages, each routed through our fusion router via run_agent-style calls:
  1. ICP + search-term generation  -> small panel Fusion (diverse, high-recall strings).
  2. Discovery (tool)               -> Firecrawl or DuckDuckGo domain discovery.
  3. Online-presence audit (tool)   -> Firecrawl deep crawl OR HTTP site audit + LLM read.
  4. Enrichment (tool)             -> business emails + site age (already in analysis).
  5. Fit scoring + angle (LLM)     -> single mixed model; light fusion optional.
  6. Package                       -> structured LeadRunResult (ICP, leads, GDPR note).

The agent def is production_ready=False and fusion=False (it's a coordinator); Fusion is
invoked internally where it helps (stage 1 panel, optional stage 5).
"""

from __future__ import annotations

import json
from typing import List, Optional

from backend.agents import run_agent
from backend.llm import LLMClient
from backend.router import route

from .discovery import (
    analyze_domain,
    analyze_domains,
    discover_candidates,
    fc_deep_analyze_domain,
    fc_discover_candidates,
    map_emails_to_business,
)
from .models import (
    DiscoveredLead,
    ICPInput,
    ICPResult,
    LeadAudit,
    LeadRunResult,
    LeadScore,
    SearchTerm,
)

# Model pins (catalog ids). Adjust freely; mirrored from other agents' posture.
ICP_FUSION_PANEL = ["or-opus", "or-ds-pro", "oa-sol"]
ICP_FUSION_JUDGE = "or-opus"
AUDIT_MODEL = "or-sonnet46"        # balanced quality, cheap, reads scraped markdown
SCORING_MODEL = "or-llama33"       # economic tier: short structured scores from long audit


# ---------------------------------------------------------------------------
# Stage 1: ICP clarification + search terms (panel Fusion)
# ---------------------------------------------------------------------------
def generate_icp(icp: ICPInput, llm: LLMClient) -> ICPResult:
    context = _icp_context(icp)
    prompt = (
        "You are a B2B lead-generation strategist. Given a client's offer and the kind of "
        "companies they want as leads, do two things:\n"
        "1) Restate the ICP clearly (who they should target and why).\n"
        "2) Generate the PERFECT Google search strings to find small, excellent-but-invisible "
        "firms in that niche. The goal is to surface companies with weak/unclear online presence "
        "or who are 'invisible next to the giants' — these are the best leads for the client's offer.\n\n"
        "Use Google operators: exact phrases in quotes, minus (-) to exclude giants, site: for "
        "directories (e.g. site:clutch.co, site:linkedin.com, site:lawsociety.org.uk), and "
        "negative keywords to strip job boards (-jobs -careers). Vary the angle per target segment.\n\n"
        f"CLIENT CONTEXT:\n{context}\n\n"
        'Reply with ONLY valid JSON of shape:\n'
        '{"clarified": str, "notes": str, "search_terms": [{"profile": str, "query": str, "why": str}]}'
    )
    messages = [{"role": "user", "content": prompt}]
    text, _ = route(
        llm, messages,
        fusion=True,
        panel=ICP_FUSION_PANEL,
        judge=ICP_FUSION_JUDGE,
        temperature=0.6,
        max_tokens=2048,
    )
    return _parse_icp(text)


def _parse_icp(text: str) -> ICPResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Strip code fences if present.
        cleaned = text.strip().strip("`").removeprefix("json").strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return ICPResult(clarified=text[:500], notes="(could not parse)", search_terms=[])
    terms = [
        SearchTerm(profile=t.get("profile", ""), query=t.get("query", ""), why=t.get("why", ""))
        for t in data.get("search_terms", [])
        if t.get("query")
    ]
    return ICPResult(clarified=data.get("clarified", ""), notes=data.get("notes", ""), search_terms=terms)


# ---------------------------------------------------------------------------
# Stage 2-4: discovery + audit + enrichment (tools)
# ---------------------------------------------------------------------------
def discover_and_audit(
    icp: ICPInput,
    search_terms: List[SearchTerm],
    llm: LLMClient,
    max_domains: int = 30,
    max_per_term: int = 8,
) -> List[DiscoveredLead]:
    regions = [icp.geography] if icp.geography else [""]
    discovered: List[str] = []
    for term in search_terms:
        if len(discovered) >= max_domains:
            break
        query = term.query
        if icp.geography and icp.geography.lower() not in query.lower():
            query = f"{query} {icp.geography}"
        if icp.use_firecrawl:
            found = fc_discover_candidates(query, num_results=max_per_term)[:max_per_term]
        else:
            found = discover_candidates(
                query, regions, limit=max_per_term, locale=_locale(icp.language),
            )[:max_per_term]
        for d in found:
            if d not in discovered:
                discovered.append(d)
        if len(discovered) >= max_domains:
            break

    leads: List[DiscoveredLead] = []
    for domain in discovered[:max_domains]:
        analysis = (
            fc_deep_analyze_domain(domain) if icp.use_firecrawl
            else analyze_domain(domain)
        )
        if analysis is None:
            continue
        emails = sorted(map_emails_to_business(analysis.emails))
        audit = _audit_domain(llm, domain, analysis, emails, use_firecrawl=icp.use_firecrawl)
        leads.append(DiscoveredLead(
            domain=domain, name="", emails=emails,
            audit=audit, score=LeadScore(),
        ))
    return leads


def _audit_domain(llm, domain, analysis, emails, *, use_firecrawl: bool) -> LeadAudit:
    """Read the scraped pages an LLM can see and classify presence/messaging gaps."""
    scrape_note = (
        "Deep-crawled with Firecrawl." if use_firecrawl
        else "Basic HTTP page discovery (homepage + contact/about pages)."
    )
    prompt = (
        "You assess a company's public online presence to find the 'invisible-but-excellent' "
        "gap: firms that are good at their craft but weak at marketing, so they are hard to find. "
        "Given the domain, estimated site age, and the business emails found, judge:\n"
        "- bloat_signal: does the site look thin? (few indexed pages, no case studies/blog)\n"
        "- messaging_clarity: is the value proposition clear from snippets? (unclear/jargon = good lead)\n"
        "- presence_gap: where do they actually live (LinkedIn-only? invisible? word-of-mouth?)\n"
        "- flags: anything notable (ex-Big4 spinoff, niche specialty, etc.)\n\n"
        f"Domain: {domain}\nSite age: {analysis.site_age_label}\n"
        f"Emails found (business only): {', '.join(emails) or 'none'}\n"
        f"Method: {scrape_note}\n\n"
        'Reply ONLY JSON: {"bloat_signal": str, "messaging_clarity": str, '
        '"presence_gap": str, "flags": [str]}'
    )
    messages = [{"role": "user", "content": prompt}]
    text, _ = route(llm, messages, model_id=AUDIT_MODEL, temperature=0.4, max_tokens=800)
    try:
        data = json.loads(text.strip().strip("`").removeprefix("json").strip())
    except json.JSONDecodeError:
        data = {}
    return LeadAudit(
        site_age_label=analysis.site_age_label,
        bloat_signal=data.get("bloat_signal", ""),
        messaging_clarity=data.get("messaging_clarity", ""),
        presence_gap=data.get("presence_gap", ""),
        flags=data.get("flags", []),
    )


# ---------------------------------------------------------------------------
# Stage 5: fit scoring + outreach angle (LLM)
# ---------------------------------------------------------------------------
def score_leads(icp: ICPInput, leads: List[DiscoveredLead], llm: LLMClient) -> List[DiscoveredLead]:
    for lead in leads:
        prompt = (
            "Score how good a lead this company is for the CLIENT's offer, and give the first "
            "outreach angle. A strong lead = small, excellent-but-invisible firm in the client's "
            "niche (weak online presence, no marketing engine, but clearly good at their craft).\n\n"
            f"CLIENT OFFER: {icp.offer}\nICP: {_icp_context(icp)}\n\n"
            f"COMPANY: {lead.domain}\nSite age: {lead.audit.site_age_label}\n"
            f"Bloat signal: {lead.audit.bloat_signal}\n"
            f"Messaging: {lead.audit.messaging_clarity}\n"
            f"Presence gap: {lead.audit.presence_gap}\nFlags: {', '.join(lead.audit.flags) or 'none'}\n\n"
            'Reply ONLY JSON: {"fit_score": int 0-100, "fit_rationale": str, '
            '"why_now": str, "suggested_angle": str}'
        )
        messages = [{"role": "user", "content": prompt}]
        text, _ = route(llm, messages, model_id=SCORING_MODEL, temperature=0.4, max_tokens=600)
        try:
            data = json.loads(text.strip().strip("`").removeprefix("json").strip())
        except json.JSONDecodeError:
            data = {}
        lead.score = LeadScore(
            fit_score=int(max(0, min(100, data.get("fit_score", 0)))),
            fit_rationale=data.get("fit_rationale", ""),
            why_now=data.get("why_now", ""),
            suggested_angle=data.get("suggested_angle", ""),
        )
    # Best leads first.
    leads.sort(key=lambda l: l.score.fit_score, reverse=True)
    return leads


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------
def run_lead_finder(icp: ICPInput, llm: LLMClient) -> LeadRunResult:
    icp_result = generate_icp(icp, llm)
    leads = discover_and_audit(icp, icp_result.search_terms, llm)
    leads = score_leads(icp, leads, llm)
    return LeadRunResult(icp=icp_result, leads=leads)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _icp_context(icp: ICPInput) -> str:
    parts = [
        f"Offer: {icp.offer or '(not specified)'}" ,
        f"Geography: {icp.geography or '(any)'}",
        f"Company size target: {icp.company_size or '(any)'}",
        f"Language: {icp.language}",
        f"Target / niche / exclusions: {icp.target_description or '(none given)'}",
    ]
    if icp.refinement:
        parts.append(f"Refinement from chat: {icp.refinement}")
    return "\n".join(parts)


def _locale(language: str) -> str:
    return {
        "en": "us-en", "de": "de-de", "es": "es-es", "fr": "fr-fr",
    }.get(language, "us-en")
