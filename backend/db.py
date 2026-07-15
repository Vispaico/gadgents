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
def get_or_create_dev_user(session: Session) -> User:
    """Synthetic user used to persist history in dev-bypass mode (REQUIRE_LOGIN=false)
    where the frontend supplies no real user. Only ever created in that mode."""
    dev_email = "__dev__@gadgents.local"
    existing = session.exec(select(User).where(User.email == dev_email)).first()
    if existing:
        return existing
    dev = User(email=dev_email, hashed_password="", credits=0, plan="dev")
    session.add(dev)
    session.commit()
    session.refresh(dev)
    return dev
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


# ===========================================================================
# Editorial AI Studio (agent #6) state: a multi-stage content engine.
# One run mines ideas from an essay, plans a calendar, then creates platform-native
# assets (4 versions each) that are humanized + quality-scored. Brand voice is a
# pluggable BrandProfile so the engine adapts to ANY brand, not just Vispaico.
# The stage SYSTEM PROMPTS live in PromptTemplate (editable, no code edits to tune).
# ===========================================================================
class BrandProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = ""
    voice_prompt: str = ""          # free-text description of the brand voice/tone
    link_url: str = ""              # the brand link to cite naturally
    forbidden_phrases: str = ""     # comma/pipe separated phrases to never use
    is_default: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EditorialRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    brand_id: int = Field(index=True)
    essay_text: str = ""            # the source essay/empirical material
    status: str = "running"         # running | done | failed | canceled
    ideas_count: int = 0
    assets_count: int = 0
    credits_used: int = 0
    error: str = ""
    canceled: bool = False          # set by the Cancel button or the guardrail
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IdeaBank(SQLModel, table=True):
    """Stage 1 output: the mined ideas for a run."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    ideas_json: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EditorialCalendar(SQLModel, table=True):
    """Stage 2 output: the selected ideas + 4-week calendar."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    calendar_json: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EditorialAsset(SQLModel, table=True):
    """Stages 3-5 output: one editable asset (one platform/idea combo), all versions
    stored as JSON in `content`. Humanized + quality-scored per asset."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    idea_ref: str = ""              # which mined idea this came from (title/id)
    platform: str = ""              # linkedin|facebook|instagram|x|newsletter|...|quotes|hooks|...
    kind: str = ""                 # post|thread|carousel|quote|hook|question|prediction|...
    content: str = ""              # JSON list of 1-4 version strings (the final, publish-ready text)
    quality_score: int = 0         # 1-10, set by the Quality Director
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PromptTemplate(SQLModel, table=True):
    """The 6 editable stage SYSTEM PROMPTS. The only 'prompt library' piece — editable
    without code changes. Seeded with defaults; the pipeline reads these if present."""
    id: Optional[int] = Field(default=None, primary_key=True)
    stage: str = ""                # idea_miner|strategist|creator|humanizer|quality_director|multiplier
    version: int = 1
    system_prompt: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Default stage system prompts (mirrored by the registered editorial agents, but
# editable via /api/editorial/templates). Kept in sync with backend/agents.py.
_EDITORIAL_STAGE_PROMPTS: dict[str, str] = {
    "idea_miner": (
        "You are the Editorial Idea Miner. Given a source essay or long text, extract 25-50 "
        "distinct, publishable ideas. For each: a short title, a one-sentence summary, an "
        "angle (controversial|useful|surprising|inspiring), and platform potentials (which "
        "of: linkedin, facebook, instagram, x, newsletter, youtube_shorts, youtube_long, "
        "podcast, quotes, hooks, questions, predictions it suits). Do NOT reference the "
        "original essay in the idea text. Reply with a single JSON object: "
        '{"ideas": [{"id": str, "title": str, "summary": str, "angle": str, '
        '"platforms": [str], "novelty": 1-10, "reach": 1-10}]}. Valid JSON only.'
    ),
    "strategist": (
        "You are the Editorial Strategist. Given an idea bank (JSON of mined ideas), apply an "
        "ANGLE-FIRST workflow: read the ideas, score EACH by authority, originality, and "
        "commercial relevance (0-10 each), then RANK them strongest-first. Pick the most "
        "diverse, highest-scoring 6-12 ideas and lay out a 4-week publishing calendar that "
        "covers them in ranked order (strongest angle first). Avoid overlap between angles. "
        "Diversify platforms. Reply with a single JSON object: "
        '{"selected": [idea_id...], "calendar": [{"week": 1-4, "idea_id": str, '
        '"platform": str, "note": str}], "ranked": [{"idea_id": str, "authority": int, '
        '"originality": int, "commercial": int}]}. Valid JSON only.'
    ),
    "creator": (
        "You are the Editorial Creator. You are given ONE idea (title + summary + angle) and "
        "must create platform-native assets for each requested platform, with EXACTLY 4 "
        "distinct versions per platform, written as if created independently (never mention "
        "the source essay). Types: linkedin/FB/IG = posts (IG as carousel slides), X = a "
        "thread, newsletter = an issue, youtube_shorts = short scripts, youtube_long = 3-10min "
        "video treatments, podcast = 2-host 1-5min outlines, quotes/hooks/questions/predictions "
        "= the requested number of one-liners. Cite the brand link naturally where relevant, "
        "but never hard-sell. Avoid the brand's forbidden phrases. Reply with a single JSON "
        'object: {"assets": [{"platform": str, "kind": str, "versions": [str...]}]}. '
        "Valid JSON only."
    ),
    "humanizer": (
        "You are the Editorial Humanizer. Take assets (platform/kind + versions) and strip all "
        "AI tells: repetitive rhythm, lazy cliches, corporate jargon, hedging, 'in conclusion'. "
        "Keep meaning. Reply with a single JSON object of the SAME shape "
        '{"assets": [{"platform": str, "kind": str, "humanized_versions": [str...]}]}. '
        "Valid JSON only."
    ),
    "quality_director": (
        "You are the Editorial Quality Director (a strict judge). Given humanized assets, score "
        "EACH asset 1-10 across specificity, voice, hook strength, platform fit, and "
        "no-AI-tells. If below 9.5, rewrite it to at least 9.5. Reply with a single JSON object: "
        '{"assets": [{"platform": str, "kind": str, "quality_score": int, '
        '"final_versions": [str...]}]}. Valid JSON only.'
    ),
    "multiplier": (
        "You are the Editorial Multiplier. Given a run's created assets, propose 5-8 NEW pieces "
        "of IP (essays, videos, talks, lead magnets) the brand could spin up next. Reply with a "
        'single JSON object: {"ip": [{"title": str, "format": str, "why": str}]}. Valid JSON only.'
    ),
}


def seed_editorial_defaults(session: Session) -> None:
    """Idempotent seeding of editorial brand profiles + stage prompt templates.
    Called from init_db. Safe to call repeatedly — brands are upserted by name and
    stage prompts synced from the canonical source, so code changes propagate."""
    # Brand profiles upserted by name (so adding HAIPHONG doesn't depend on the
    # default brand being absent).
    EDITORIAL_BRANDS = [
        BrandProfile(
            name="Vispaico",
            voice_prompt=(
                "Confident, calm, founder-to-founder. No hype, no jargon, never promotional or loud. "
                "Teaches the reader something genuinely useful about AI operating systems and "
                "agentic workflows, then lets the product speak for itself. Write like a senior "
                "operator with a point of view, not a marketer growing followers. Never simply "
                "summarize — multiply the essay's value into original pieces others will want to share."
            ),
            link_url="https://www.vispaico.com/en/aios",
            forbidden_phrases=(
                "game-changer|revolutionary|cutting-edge|leverage synergy|in today's fast-paced world|"
                "unlock|secret|growth hack|dominate|crushing it|scale fast|disruptive|here's why|"
                "whether you're"
            ),
            is_default=True,
        ),
        BrandProfile(
            name="Made in HAIPHONG",
            voice_prompt=(
                "You are the Chief Content Strategist for Made in HAIPHONG, a premium strategic "
                "consultancy that helps ambitious companies become the obvious choice through "
                "Authority, Presence, Influence and Growth. The market rarely rewards the best "
                "company; it rewards the one people notice, remember and trust. Calm, elegant, "
                "thoughtful, confident, intelligent, measured, sophisticated. Never promotional, "
                "never loud, never motivational, never 'LinkedIn influencer', never 'marketing guru'. "
                "Do NOT sell or pitch; authority is built through ideas. Reference Made in HAIPHONG "
                "at most once, only if natural. Multiply the essay's commercial and intellectual "
                "value into original content; never just shorten it. Every asset must stand alone "
                "and create one moment where the reader thinks 'I've never considered it that way.'"
            ),
            link_url="",
            forbidden_phrases=(
                "game-changer|revolutionary|unlock|leverage|secret|growth hack|crushing it|dominate|"
                "scale fast|disruptive|in today's world|in the digital age|here's why|whether you're|"
                "in today's fast-paced world"
            ),
            is_default=False,
        ),
        BrandProfile(
            name="Untitled Brand",
            voice_prompt="Clear, helpful, native to each platform. Match the source voice; do not invent facts.",
            link_url="",
            forbidden_phrases="",
            is_default=False,
        ),
    ]
    for b in EDITORIAL_BRANDS:
        existing = session.exec(select(BrandProfile).where(BrandProfile.name == b.name)).first()
        if existing is None:
            session.add(b)
        else:
            existing.voice_prompt = b.voice_prompt
            existing.link_url = b.link_url
            existing.forbidden_phrases = b.forbidden_phrases
            # Only set is_default from the seed for the Vispaico entry; never unset a
            # user's chosen default.
            if b.is_default:
                existing.is_default = True
            session.add(existing)
    session.commit()

    for stage, prompt in _EDITORIAL_STAGE_PROMPTS.items():
        existing = session.exec(select(PromptTemplate).where(PromptTemplate.stage == stage)).first()
        if existing is None:
            session.add(PromptTemplate(stage=stage, version=1, system_prompt=prompt))
        elif existing.system_prompt.strip() != prompt.strip():
            # Always sync the stage prompt from the canonical source so prompt improvements
            # in code propagate on the next init_db(). (Also repairs any short/corrupt row.)
            existing.system_prompt = prompt
            existing.version += 1
            session.add(existing)
    try:
        session.commit()
    except Exception:
        session.rollback()


engine = None


def get_engine() -> "create_engine":
    global engine
    if engine is None:
        from backend.config import get_settings

        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        engine = create_engine(url, connect_args=connect_args)
    return engine


def _ensure_columns() -> None:
    """Add any columns that were introduced after an existing SQLite DB was created.

    SQLModel's create_all only creates NEW tables; it never ALTERs existing ones, so a
    dev DB from before these columns were added would otherwise fail on insert. We
    reconcile the on-disk schema with the model metadata per column. Safe to run every
    startup; it only adds what's missing."""
    eng = get_engine()
    inspector = __import__("sqlalchemy").inspect(eng)
    with eng.begin() as conn:
        for table in SQLModel.metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    # Resolve the column's DB type via the dialect.
                    from sqlalchemy import dialects

                    sqlite_dialect = dialects.sqlite.dialect()
                    col_type = column.type.compile(dialect=sqlite_dialect)
                    # NOTE: SQLite ALTER TABLE can only add NULLable columns, so we do
                    # not emit NOT NULL (missing rows get the Python-side default at
                    # insert time). Server-side defaults, if any, are appended.
                    default = (
                        f" DEFAULT {column.server_default.arg}"
                        if column.server_default is not None
                        else ""
                    )
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                            f"{col_type}{default}"
                        )
                    )


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
    _ensure_columns()
    # Idempotent seed of editorial defaults (brand profiles + stage prompt templates).
    with Session(get_engine()) as _seed_session:
        seed_editorial_defaults(_seed_session)


def get_session():
    with Session(get_engine()) as session:
        yield session


def get_user_by_email(session: Session, email: str) -> Optional[User]:
    return session.exec(select(User).where(User.email == email)).first()


def get_user(session: Session, user_id: int) -> Optional[User]:
    return session.get(User, user_id)


# ===========================================================================
# Social Listener (agent #5) state: a topic query + the posts it pulled.
# Posts are scraped via CloakBrowser (stealth Chromium) from X / LinkedIn using a
# persistent logged-in profile. Engagement fields drive client-side sorting.
# NOTE: scraping another platform's posts via an authenticated session carries ToS
# and ban risk; that's a user-accepted product decision, not a code concern.
# ===========================================================================
class SocialQuery(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    topic: str = ""               # the search/topic the user asked for
    platforms: str = ""           # csv: x|linkedin
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SocialPost(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    query_id: int = Field(index=True)
    user_id: int = Field(index=True)
    platform: str = ""             # x | linkedin
    author: str = ""
    text: str = ""
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    url: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

