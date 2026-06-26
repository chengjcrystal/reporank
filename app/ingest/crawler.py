"""GitHub repository crawler.

Two problems any real GitHub crawler must solve, both handled here:

1. The 1000-results-per-query cap. The Search API never returns more than 1000
   results for a single query, no matter the pagination. We beat this by SLICING
   the corpus into many narrow star-range buckets (stars:100..149, 150..199, ...)
   so each slice stays under 1000 and the union covers the whole range.

2. Rate limits. Authenticated search is 30 req/min. We read the response headers
   (X-RateLimit-Remaining / -Reset) and sleep until reset when we run dry, plus
   honor 403/secondary-limit backoff.

Progress is checkpointed per slice in `crawl_state`, so a crash resumes instead
of restarting.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.normalize import upsert_repository
from app.models import CrawlState

API = "https://api.github.com"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _respect_rate_limit(resp: httpx.Response) -> None:
    """Sleep if we're about to exceed the rate limit."""
    remaining = int(resp.headers.get("X-RateLimit-Remaining", "1"))
    if remaining <= 0:
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
        wait = max(1, reset - int(time.time())) + 1
        print(f"  rate limit hit; sleeping {wait}s")
        time.sleep(wait)


def _star_slices(min_stars: int, max_stars: int, step: int):
    """Yield star-range query fragments covering [min_stars, max_stars]."""
    lo = min_stars
    while lo <= max_stars:
        hi = min(lo + step - 1, max_stars)
        if hi >= max_stars:
            yield f"stars:>={lo}"   # open-ended top bucket
            return
        yield f"stars:{lo}..{hi}"
        lo = hi + 1


def crawl(
    db: Session,
    language: str | None = None,
    min_stars: int = 100,
    max_stars: int = 200000,
    star_step: int = 50,
    max_repos: int = 5000,
    per_page: int = 100,
) -> int:
    """Crawl repos into Postgres. Returns number of repos upserted."""
    if not settings.github_token:
        print("WARNING: no GITHUB_TOKEN set; unauthenticated limit is 60 req/hr.")

    total = 0
    base = f"language:{language} " if language else ""

    with httpx.Client(headers=_headers(), timeout=30.0) as client:
        for star_q in _star_slices(min_stars, max_stars, star_step):
            if total >= max_repos:
                break
            query = f"{base}{star_q} fork:false"
            state = _get_or_create_state(db, query)
            if state.status == "complete":
                continue
            state.status = "running"
            db.commit()

            page = state.last_page + 1
            while total < max_repos:
                resp = client.get(
                    f"{API}/search/repositories",
                    params={"q": query, "sort": "stars", "order": "desc",
                            "per_page": per_page, "page": page},
                )
                if resp.status_code == 403:
                    _respect_rate_limit(resp)
                    time.sleep(5)
                    continue
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    break

                for raw in items:
                    upsert_repository(db, raw)
                    total += 1
                    state.repos_fetched += 1

                state.last_page = page
                state.last_run_at = datetime.now(timezone.utc)
                db.commit()
                print(f"  [{query}] page {page}: +{len(items)} (total {total})")

                _respect_rate_limit(resp)
                if len(items) < per_page or page >= 10:  # 10*100 = 1000 cap
                    break
                page += 1

            state.status = "complete"
            db.commit()

    print(f"Crawl finished: {total} repositories upserted.")
    return total


def _get_or_create_state(db: Session, strategy: str) -> CrawlState:
    state = db.query(CrawlState).filter(CrawlState.strategy == strategy).one_or_none()
    if state is None:
        state = CrawlState(strategy=strategy, status="pending")
        db.add(state)
        db.commit()
    return state
