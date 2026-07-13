from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session, select


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    credits: int = Field(default=0)  # remaining spendable credits
    plan: str = Field(default="free")  # free | hourly | monthly
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = Field(default=True)


class Usage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    agent_id: str
    credits_used: int
    tokens_in: int = 0
    tokens_out: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Subscription(SQLModel, table=True):
    """Long-term subscription record (populated via Stripe webhook in live mode)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    plan: str  # hourly | monthly
    provider: str = "mock"  # mock | stripe
    status: str = "active"  # active | canceled
    external_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ===========================================================================
# Proactive secretary subsystem (agent #1). The personal-planner agent is the
# "brain"; these models are the state it reads/writes so a future scheduled
# reminder loop + delivery channel can drive it. Designed channel-agnostic.
# ===========================================================================

# Item kinds the capture layer classifies everything into.
ItemKind = str  # task | appointment | idea | reference | waiting_on | someday


class InboxItem(SQLModel, table=True):
    """Raw brain-dump before classification."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    raw_text: str
    source: str = "chat"  # chat | url | screenshot | note
    kind: Optional[str] = None  # filled after classification
    status: str = "new"  # new | processed | archived
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str
    goal: str = ""
    status: str = "active"  # active | done | paused
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    project_id: Optional[int] = None
    title: str
    next_action: str = ""  # the single concrete next step
    duration_min: int = 30
    urgency: int = Field(default=3, ge=1, le=5)  # 1 low .. 5 now
    confidence: int = Field(default=3, ge=1, le=5)  # how sure the plan is right
    status: str = "open"  # open | scheduled | done | deferred | dropped
    due: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CalendarEvent(SQLModel, table=True):
    """Hard external commitment (birthday, meeting) the plan must respect."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    title: str
    start: datetime
    end: datetime
    source: str = "user"


class TimeBlock(SQLModel, table=True):
    """A slot on the day plan. May be linked to a task or be a protected focus block."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    task_id: Optional[int] = None
    title: str
    start: datetime
    end: datetime
    kind: str = "task"  # focus | admin | deep_work | break | disruption
    focus: bool = False  # protected deep-work block


class Reminder(SQLModel, table=True):
    """One escalation stage of a nudge. The loop fires due reminders, escalates,
    then auto-reslots if ignored."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    task_id: Optional[int] = None
    trigger_at: datetime
    stage: int = 1  # 1 soft nudge .. 3 "snooze or commit?" .. 4 auto-reslot
    channel: str = "inbox"  # inbox | email | webhook (delivery wired later)
    message: str = ""
    status: str = "pending"  # pending | sent | done | skipped
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeItem(SQLModel, table=True):
    """Captured URLs / copy / screenshots the secretary makes sense of later."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    content: str
    kind: str = "url"  # url | copy | screenshot | note
    topic: str = ""
    usefulness: int = Field(default=3, ge=1, le=5)
    relevance: str = "business"  # business | private | both
    action_type: str = ""  # content_idea | sales_lead | tool_to_test | process | interest
    source: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DailyReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    day: datetime
    summary: str = ""
    backlog_cleanup: str = ""
    patterns: str = ""


class PlannerMemory(SQLModel, table=True):
    """Learning layer: stable preferences the agent adapts over time.
    key examples: tone, focus_protection, working_hours, snooze_style, replan_aggressiveness."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    key: str
    value: str  # JSON-encoded preference
    confidence: int = Field(default=2, ge=1, le=5)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def set_memory(session: Session, user_id: int, key: str, value: str, confidence: int = 2) -> None:
    existing = session.exec(
        select(PlannerMemory).where(PlannerMemory.user_id == user_id, PlannerMemory.key == key)
    ).first()
    if existing:
        existing.value = value
        existing.confidence = confidence
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        session.add(PlannerMemory(user_id=user_id, key=key, value=value, confidence=confidence))
    session.commit()


def get_memories(session: Session, user_id: int) -> list[PlannerMemory]:
    return list(session.exec(select(PlannerMemory).where(PlannerMemory.user_id == user_id)).all())


# ===========================================================================
# Content Repurposer (agent #2) state: canonical brief + per-channel outputs.
# ===========================================================================
class ContentBrief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    source_title: str = ""
    source_text: str = ""         # truncated original for reference
    channels: str = ""            # csv of requested channels
    tone: str = ""
    audience: str = ""
    brief_json: str = ""          # the structured brief JSON
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContentOutput(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    brief_id: int = Field(index=True)
    user_id: int = Field(index=True)
    channel: str = ""             # linkedin|facebook|x|instagram|youtube|shorts_tiktok|script|media
    variant_index: int = 0
    content_json: str = ""        # per-channel JSON or script package
    model: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ===========================================================================
# Wan2.2 Image-to-Video Prompt (agent #4) state: canonical brief + per-shot prompts.
# ===========================================================================
class WanVideoBrief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    title: str = ""
    source_image: str = ""        # url/data-ref of the seed image (kept as ref only)
    concept: str = ""             # the concept / script / mood text
    format_kind: str = ""         # ad | short_film | doc | podcast | reel | "" (tuning hook)
    brief_json: str = ""          # full structured storyboard JSON
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WanVideoShot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    brief_id: int = Field(index=True)
    user_id: int = Field(index=True)
    shot_number: int = 0
    camera: str = ""              # move name from vocabulary
    frame: str = ""
    action: str = ""
    look: str = ""
    wan_prompt: str = ""          # ready-to-paste Wan2.2 image-to-video prompt
    model: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ===========================================================================
# Lead Finder (agent #3) state: persisted ICP runs + discovered leads.
# Sourced from public web only (scrape public sites + business emails); GDPR-safe.
# ===========================================================================
class LeadQuery(SQLModel, table=True):
    """One ICP definition + the search terms the agent generated for it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = ""                           # human label for the run
    offer: str = ""                          # what the client sells
    geography: str = ""                       # locality / region added to queries
    target_description: str = ""             # free-text ICP / niches / exclusions
    company_size: str = ""                   # e.g. "11-50", "1-10"
    language: str = "en"
    search_terms_json: str = ""              # list[str] of generated Google search strings
    raw_notes: str = ""                      # agent's ICP rationale / notes
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Lead(SQLModel, table=True):
    """A discovered + scored company/lead for a given query run."""
    id: Optional[int] = Field(default=None, primary_key=True)
    query_id: int = Field(index=True)
    user_id: int = Field(index=True)
    domain: str = ""
    name: str = ""                           # business name if known
    emails_json: str = ""                    # list[str] business emails found
    site_age_label: str = ""
    audit_json: str = ""                     # online-presence audit (bloat, messaging, flags)
    fit_score: int = 0                       # 0-100 agent fit score
    fit_rationale: str = ""
    why_now: str = ""                        # the "invisible but excellent" gap angle
    suggested_angle: str = ""                # first outreach angle for the client
    status: str = "new"                      # new | contacted | rejected | archived
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


engine = None


def get_engine() -> "create_engine":
    global engine
    if engine is None:
        from backend.config import get_settings

        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, connect_args=connect_args)
    return engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.exec(select(User).where(User.email == email)).first()


def get_user(session: Session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)
