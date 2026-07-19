"""Social Listener endpoint (agent #5).

Runs the CloakBrowser listener for chosen platforms + topic, persists the query + posts,
and lists past queries/posts. Engagement counts are returned so the frontend can sort.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.auth import get_current_user
from backend.config import get_settings
from backend.db import (
    User,
    get_session,
    SocialQuery,
    SocialPost,
    get_or_create_dev_user,
)
from backend.social import listen as run_listen

router = APIRouter(prefix="/api/social", tags=["social"])

_settings = get_settings()

VALID_PLATFORMS = ["x", "linkedin"]


@router.post("/listen")
def listen(
    topic: str = Body(..., embed=True),
    platforms: list[str] = Body(["x"]),
    limit: int = Body(20),
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login:
        user = None
    effective = user or get_or_create_dev_user(session)
    if not topic.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="topic required")

    chosen = [p for p in platforms if p in VALID_PLATFORMS] or ["x"]
    posts = run_listen(chosen, topic.strip(), limit)

    query = SocialQuery(
        user_id=effective.id,
        topic=topic.strip(),
        platforms=",".join(chosen),
    )
    session.add(query)
    session.commit()
    session.refresh(query)

    for post in posts:
        session.add(SocialPost(
            query_id=query.id,
            user_id=effective.id,
            platform=post.get("platform", ""),
            author=post.get("author", ""),
            text=post.get("text", ""),
            like_count=post.get("like_count", 0),
            repost_count=post.get("repost_count", 0),
            reply_count=post.get("reply_count", 0),
            url=post.get("url", ""),
        ))
    session.commit()

    return {
        "query_id": query.id,
        "count": len(posts),
        "posts": posts,
    }


@router.get("/queries")
def list_queries(
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    rows = session.exec(
        select(SocialQuery).where(SocialQuery.user_id == user.id)
        .order_by(SocialQuery.created_at.desc())
    ).all()
    return [
        {"id": r.id, "topic": r.topic, "platforms": r.platforms, "created_at": str(r.created_at)}
        for r in rows
    ]


@router.delete("/queries/{query_id}")
def delete_query(
    query_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    query = session.get(SocialQuery, query_id)
    if query is None or query.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    # Cascade-delete the posts belonging to this query.
    for post in session.exec(select(SocialPost).where(SocialPost.query_id == query_id)).all():
        session.delete(post)
    session.delete(query)
    session.commit()
    return {"deleted": query_id}


@router.get("/queries/{query_id}/posts")
def list_posts(
    query_id: int,
    user: User = Depends(get_current_user) if _settings.require_login else None,
    session: Session = Depends(get_session),
):
    if not _settings.require_login or user is None:
        user = get_or_create_dev_user(session)
    query = session.get(SocialQuery, query_id)
    if query is None or query.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    rows = session.exec(
        select(SocialPost).where(SocialPost.query_id == query_id)
        .order_by(SocialPost.like_count.desc())
    ).all()
    return [
        {
            "id": r.id, "platform": r.platform, "author": r.author, "text": r.text,
            "like_count": r.like_count, "repost_count": r.repost_count,
            "reply_count": r.reply_count, "url": r.url,
        }
        for r in rows
    ]
