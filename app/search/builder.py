"""Build the inverted index from the database (the source of truth)."""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repository
from app.search.index import DocMeta, InvertedIndex


def build_index(db: Session) -> tuple[InvertedIndex, dict]:
    """Build the full index. Returns (index, build_stats)."""
    start = time.time()
    index = InvertedIndex()

    repos = db.scalars(select(Repository)).all()
    for repo in repos:
        meta = DocMeta(
            stars=repo.stars or 0,
            forks=repo.forks or 0,
            language=repo.primary_language,
            topics=tuple(t.name for t in repo.topics),
            pushed_at=repo.pushed_at.timestamp() if repo.pushed_at else None,
        )
        index.add_document(repo.id, repo.search_document or "", meta)

    index.finalize()
    stats = {
        "documents": index.N,
        "vocabulary": index.vocabulary_size(),
        "postings": index.total_postings(),
        "avg_doc_len": round(index.avg_doc_len, 2),
        "build_seconds": round(time.time() - start, 3),
    }
    return index, stats
