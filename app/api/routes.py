"""HTTP API routes."""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.state import state
from app.db import get_session
from app.models import Repository, SearchLog, Topic
from app.schemas import (
    ClickEvent, FiltersResponse, RepoResult, SearchResponse, SuggestResponse,
)
from app.search.engine import DEFAULT_RANKER, Filters, RANKERS

router = APIRouter(prefix="/api")


def _to_result(repo: Repository, score: float, bm25: float) -> RepoResult:
    return RepoResult(
        id=repo.id,
        full_name=repo.full_name,
        description=repo.description,
        stars=repo.stars,
        forks=repo.forks,
        language=repo.primary_language,
        topics=repo.topic_names(),
        pushed_at=repo.pushed_at,
        html_url=repo.html_url,
        score=round(score, 4),
        bm25=round(bm25, 4),
    )


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query("", description="Search query"),
    language: str | None = None,
    min_stars: int | None = None,
    topics: str | None = Query(None, description="Comma-separated topics (AND)"),
    updated_after: str | None = Query(None, description="ISO date, e.g. 2025-01-01"),
    ranker: str = DEFAULT_RANKER,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
):
    engine = state.require()
    if ranker not in RANKERS:
        ranker = DEFAULT_RANKER

    updated_ts = None
    if updated_after:
        try:
            updated_ts = datetime.fromisoformat(updated_after).timestamp()
        except ValueError:
            raise HTTPException(400, "updated_after must be ISO format (YYYY-MM-DD)")

    filters = Filters(
        language=language,
        min_stars=min_stars,
        topics=tuple(t.strip() for t in topics.split(",")) if topics else (),
        updated_after=updated_ts,
    )

    start = time.perf_counter()
    hits, total = engine.search(q, filters=filters, ranker=ranker,
                                page=page, per_page=per_page)
    latency_ms = (time.perf_counter() - start) * 1000

    # Hydrate display fields for the page of results only.
    ids = [h.doc_id for h in hits]
    repos = {r.id: r for r in db.scalars(select(Repository).where(Repository.id.in_(ids)))} if ids else {}
    results = [_to_result(repos[h.doc_id], h.score, h.bm25) for h in hits if h.doc_id in repos]

    # Log the search for analytics + offline ranking evaluation.
    db.add(SearchLog(
        query=q, filters={"language": language, "min_stars": min_stars, "topics": topics},
        result_count=total, latency_ms=int(latency_ms), ranker_variant=ranker,
    ))
    db.commit()

    return SearchResponse(
        query=q, total=total, page=page, per_page=per_page,
        latency_ms=round(latency_ms, 2), ranker=ranker, results=results,
    )


@router.get("/repos/{repo_id}", response_model=RepoResult)
def get_repo(repo_id: int, db: Session = Depends(get_session)):
    repo = db.get(Repository, repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    return _to_result(repo, 0.0, 0.0)


@router.get("/repos/{repo_id}/similar", response_model=list[RepoResult])
def similar(repo_id: int, limit: int = Query(10, ge=1, le=50),
            db: Session = Depends(get_session)):
    """Content similarity via topic Jaccard + language match.

    A lightweight stand-in for embedding-based similarity (the semantic-search
    phase): score every other repo by shared-topic overlap, lightly boosted when
    the primary language matches.
    """
    engine = state.require()
    meta = engine.index.doc_meta
    base = meta.get(repo_id)
    if base is None:
        raise HTTPException(404, "Repository not indexed")

    base_topics = set(base.topics)
    if not base_topics:
        raise HTTPException(400, "Repository has no topics to compare")

    scored: list[tuple[int, float]] = []
    for other_id, m in meta.items():
        if other_id == repo_id:
            continue
        other_topics = set(m.topics)
        if not other_topics:
            continue
        inter = len(base_topics & other_topics)
        if inter == 0:
            continue
        union = len(base_topics | other_topics)
        jaccard = inter / union
        lang_boost = 0.1 if m.language and m.language == base.language else 0.0
        scored.append((other_id, jaccard + lang_boost))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]
    repos = {r.id: r for r in db.scalars(
        select(Repository).where(Repository.id.in_([i for i, _ in top])))}
    return [_to_result(repos[i], s, 0.0) for i, s in top if i in repos]


@router.get("/suggest", response_model=SuggestResponse)
def suggest(q: str = Query("", min_length=1), limit: int = Query(8, ge=1, le=20),
            db: Session = Depends(get_session)):
    """Prefix/substring autocomplete over repo names and topics."""
    ql = q.lower()
    names = db.scalars(
        select(Repository.full_name)
        .where(func.lower(Repository.full_name).like(f"%{ql}%"))
        .order_by(Repository.stars.desc())
        .limit(limit)
    ).all()
    topic_names = db.scalars(
        select(Topic.name).where(func.lower(Topic.name).like(f"{ql}%")).limit(limit)
    ).all()

    seen, out = set(), []
    for s in list(names) + list(topic_names):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return SuggestResponse(query=q, suggestions=out[:limit])


@router.get("/filters", response_model=FiltersResponse)
def filters(db: Session = Depends(get_session)):
    """Facet values for the UI: available languages and the most common topics."""
    langs = db.scalars(
        select(Repository.primary_language)
        .where(Repository.primary_language.is_not(None))
        .distinct()
    ).all()
    top_topics = db.execute(
        select(Topic.name, func.count().label("c"))
        .join(Topic.repositories)
        .group_by(Topic.name)
        .order_by(func.count().desc())
        .limit(40)
    ).all()
    return FiltersResponse(
        languages=sorted(langs),
        topics=[name for name, _ in top_topics],
    )


@router.post("/events/click")
def click(event: ClickEvent, db: Session = Depends(get_session)):
    """Record a result click — powers CTR for ranking evaluation."""
    db.add(SearchLog(
        query=event.query, ranker_variant=event.ranker,
        clicked_repo=event.repo_id, result_count=0, latency_ms=0,
    ))
    db.commit()
    return {"ok": True}


@router.get("/stats")
def stats(db: Session = Depends(get_session)):
    """Analytics dashboard data."""
    engine = state.engine
    total_searches = db.query(SearchLog).filter(SearchLog.clicked_repo.is_(None)).count()
    total_clicks = db.query(SearchLog).filter(SearchLog.clicked_repo.is_not(None)).count()

    top_queries = db.execute(
        select(SearchLog.query, func.count().label("c"))
        .where(SearchLog.query != "", SearchLog.clicked_repo.is_(None))
        .group_by(SearchLog.query)
        .order_by(func.count().desc())
        .limit(10)
    ).all()

    zero_results = db.query(SearchLog).filter(
        SearchLog.result_count == 0, SearchLog.clicked_repo.is_(None), SearchLog.query != ""
    ).count()

    latencies = db.scalars(
        select(SearchLog.latency_ms).where(SearchLog.clicked_repo.is_(None))
    ).all()
    latencies = sorted(latencies)

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(p * len(latencies)))
        return float(latencies[idx])

    return {
        "repositories_indexed": engine.index.N if engine else 0,
        "vocabulary_size": engine.index.vocabulary_size() if engine else 0,
        "total_searches": total_searches,
        "total_clicks": total_clicks,
        "ctr": round(total_clicks / total_searches, 3) if total_searches else 0.0,
        "zero_result_searches": zero_results,
        "latency_p50_ms": pct(0.50),
        "latency_p95_ms": pct(0.95),
        "top_queries": [{"query": q, "count": c} for q, c in top_queries],
    }
