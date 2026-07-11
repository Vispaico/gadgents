"""Pydantic models for the Lead Finder agent."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ICPInput(BaseModel):
    """Client-configurable ideal-customer-profile, plus free-form nuance.

    The frontend exposes structured fields AND a chat panel. Either path fills
    this model; the agent uses whichever is provided to refine the other."""
    name: str = Field(default="", description="Label for this lead run")
    offer: str = Field(default="", description="What the client sells (their service/product)")
    geography: str = Field(default="", description="Locality/region appended to search strings")
    target_description: str = Field(
        default="",
        description="Free-text ICP: target niches/industries, company size, exclusions, language",
    )
    company_size: str = Field(default="", description="e.g. '11-50', '1-10', '' for any")
    language: str = Field(default="en")
    # Optional chat-refinement note appended to the ICP before generation.
    refinement: Optional[str] = Field(default=None)
    # Whether to use the local Firecrawl docker for JS-rendered discovery + deep audit.
    use_firecrawl: bool = Field(default=False)


class SearchTerm(BaseModel):
    profile: str                 # which target segment this string targets
    query: str                   # copy-paste Google search string (locality added)
    why: str                     # why this surfaces weak-but-excellent firms


class ICPResult(BaseModel):
    clarified: str               # agent's restatement of the ICP after refinement
    notes: str                   # strategy notes / what to watch for
    search_terms: list[SearchTerm]


class LeadAudit(BaseModel):
    site_age_label: str = ""
    pages_indexed: Optional[int] = None
    bloat_signal: str = ""        # Website Bloat Test result (few indexed pages, no case studies)
    messaging_clarity: str = ""   # Unclear Messaging Filter result
    presence_gap: str = ""        # where the firm lives instead (LinkedIn / invisible)
    flags: list[str] = Field(default_factory=list)


class LeadScore(BaseModel):
    fit_score: int = Field(default=0, ge=0, le=100)
    fit_rationale: str = ""
    why_now: str = ""             # the invisible-but-excellent gap = the trigger
    suggested_angle: str = ""     # first outreach angle for the client


class DiscoveredLead(BaseModel):
    domain: str
    name: str = ""
    emails: list[str] = Field(default_factory=list)
    audit: LeadAudit
    score: LeadScore


class LeadRunResult(BaseModel):
    icp: ICPResult
    leads: list[DiscoveredLead]
    gdpr_note: str = (
        "Public-web only: business emails and public pages only. To build a compliant "
        "contact list at scale (incl. phone/verified mobile under GDPR/UK PECR), run the "
        "manual Cognism enrichment step separately with Do-Not-Call and business-email filters; "
        "this agent does not harvest personal data."
    )
