"""Lead Finder agent package (agent #3).

An orchestrator chain (mirrors backend.pipeline.run_content_pipeline) that turns a
client's ICP into: (1) a set of perfect Google search strings, (2) discovered
domains via public web search, (3) an online-presence audit per domain, (4) a
fit score + outreach angle. Search the public web only and collect business emails
only: no scraping of personal data, no paid B2B-data enrichment. Cognism-style
enrichment is a documented manual follow-up step.

Reuses the discovery + analysis routines from the user's Scraper toolkit
(websearch_utils: Firecrawl-backed Google discovery + domain/email/site-age
analysis) so we don't reinvent scraping. Heavy lifting is done by whichever of
our LLM models the agent's stages route to.
"""
