"""Drive the existing crawler across several languages to build a real corpus.

Loops the resumable crawler over a fixed language set, star-slicing each one, and
prints a per-language + overall summary at the end (repos upserted, wall-clock,
and the crawl_state rows that back the resume/backoff story). The crawler itself
is unchanged; this just sequences it and tallies the results.

Run from the repo root so the relative SQLite path and `app` imports resolve:
    .venv/bin/python scripts/crawl_multi.py
"""
from __future__ import annotations

import time

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import CrawlState, Repository
from app.ingest.crawler import crawl

LANGUAGES = ["python", "javascript", "typescript", "go", "rust", "java", "c++"]
MIN_STARS = 50
MAX_STARS = 2000        # above this, the open-ended top slice sweeps the rest
STAR_STEP = 25          # finer slices in the dense low-star range
MAX_REPOS_PER_LANG = 40000


def repo_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Repository))


def main() -> None:
    init_db()
    db = SessionLocal()
    wall_start = time.time()
    per_language: dict[str, int] = {}

    try:
        before_total = repo_count(db)
        print(f"starting corpus size: {before_total} repos "
              f"(includes {before_total} pre-existing rows)")

        for lang in LANGUAGES:
            print(f"\n===== crawling language={lang} "
                  f"(stars:>={MIN_STARS}, step={STAR_STEP}) =====", flush=True)
            t0 = time.time()
            upserted = crawl(
                db,
                language=lang,
                min_stars=MIN_STARS,
                max_stars=MAX_STARS,
                star_step=STAR_STEP,
                max_repos=MAX_REPOS_PER_LANG,
            )
            dt = time.time() - t0
            per_language[lang] = upserted
            print(f"  language={lang}: {upserted} upserted in {dt/60:.1f} min", flush=True)

        after_total = repo_count(db)
        states = db.scalars(select(CrawlState)).all()
        complete = sum(1 for s in states if s.status == "complete")
        fetched = sum(s.repos_fetched for s in states)

        wall = time.time() - wall_start
        print("\n================ CRAWL SUMMARY ================")
        print(f"wall-clock:            {wall/60:.1f} min")
        print(f"repos in DB after:     {after_total}  (before: {before_total})")
        print(f"net new (by DB count): {after_total - before_total}")
        print(f"sum upserted (w/ dup overwrites counted): {sum(per_language.values())}")
        print("per-language upserted (crawler return, dups re-counted):")
        for lang in LANGUAGES:
            print(f"  {lang:12} {per_language.get(lang, 0)}")
        print(f"crawl_state buckets:   {len(states)} total, {complete} complete")
        print(f"crawl_state repos_fetched (sum): {fetched}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
