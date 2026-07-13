"""Lead Finder agent: persistence + run wrapper around the orchestrator chain."""

from __future__ import annotations

import json
from typing import Optional

from sqlmodel import Session

from backend.db import Lead, LeadQuery, User
from backend.llm import LLMClient

from .models import ICPInput, LeadRunResult
from .pipeline import run_lead_finder


def run_and_persist(icp: ICPInput, llm: LLMClient, session: Session,
                    user: Optional[User] = None,
                    mode: Optional[str] = None) -> LeadRunResult:
    result = run_lead_finder(icp, llm, mode=mode)

    user_id = user.id if user else 0
    query = LeadQuery(
        user_id=user_id,
        name=icp.name or icp.offer or "lead run",
        offer=icp.offer,
        geography=icp.geography,
        target_description=icp.target_description,
        company_size=icp.company_size,
        language=icp.language,
        search_terms_json=json.dumps(
            [t.model_dump() for t in result.icp.search_terms], ensure_ascii=False
        ),
        raw_notes=result.icp.notes,
    )
    session.add(query)
    session.commit()
    session.refresh(query)

    for lead in result.leads:
        session.add(Lead(
            query_id=query.id,
            user_id=user_id,
            domain=lead.domain,
            name=lead.name,
            emails_json=json.dumps(lead.emails, ensure_ascii=False),
            site_age_label=lead.audit.site_age_label,
            audit_json=json.dumps(lead.audit.model_dump(), ensure_ascii=False),
            fit_score=lead.score.fit_score,
            fit_rationale=lead.score.fit_rationale,
            why_now=lead.score.why_now,
            suggested_angle=lead.score.suggested_angle,
            status="new",
        ))
    session.commit()
    return result
