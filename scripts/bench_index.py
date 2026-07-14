"""Measure how the inverted index scales with corpus size.

Builds the index over increasing prefixes of the corpus (ordered by stars desc so
each size is a deterministic superset of the last) and records build time, vocab
size, posting count, and on-disk snapshot footprint at each size. Produces a
scaling curve, not a single data point.

The largest build is also saved to the real snapshot path so downstream steps
(the API, the latency harness) serve the full corpus.

Run from the repo root:
    .venv/bin/python scripts/bench_index.py
"""
from __future__ import annotations

import os
import time
import tempfile
import tracemalloc

from sqlalchemy import select, func

from app.config import settings
from app.db import SessionLocal
from app.models import Repository
from app.search.index import DocMeta, InvertedIndex

# Corpus sizes to sample for the curve. Clamped to the real corpus size at runtime.
SIZES = [1_000, 5_000, 20_000, 50_000, 100_000, 200_000]


def build_over(repos) -> tuple[InvertedIndex, float, int]:
    """Build an index over an iterable of Repository rows. Returns (index,
    build_seconds, peak_bytes) where peak_bytes is the Python-heap peak measured
    with tracemalloc during the build."""
    tracemalloc.start()
    t0 = time.perf_counter()
    index = InvertedIndex()
    for repo in repos:
        meta = DocMeta(
            stars=repo.stars or 0,
            forks=repo.forks or 0,
            language=repo.primary_language,
            topics=tuple(t.name for t in repo.topics),
            pushed_at=repo.pushed_at.timestamp() if repo.pushed_at else None,
        )
        index.add_document(repo.id, meta=meta, fields={
            "name": repo.name or "",
            "description": repo.description or "",
            "topics": " ".join(t.name for t in repo.topics),
            "readme": (repo.readme_text or "")[:4000],
        })
    index.finalize()
    build_seconds = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return index, build_seconds, peak


def snapshot_bytes(index: InvertedIndex) -> int:
    fd, path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    try:
        index.save(path)
        return os.path.getsize(path)
    finally:
        os.remove(path)


def main() -> None:
    db = SessionLocal()
    try:
        total = db.scalar(select(func.count()).select_from(Repository))
        sizes = [n for n in SIZES if n < total] + [total]
        print(f"corpus size: {total} repos")
        print(f"{'repos':>8}  {'build_s':>8}  {'vocab':>9}  {'postings':>10}  "
              f"{'snapshot_MB':>11}  {'heap_peak_MB':>12}  {'us_per_doc':>10}")

        rows = []
        for n in sizes:
            repos = db.scalars(
                select(Repository).order_by(Repository.stars.desc()).limit(n)
            ).all()
            index, secs, peak = build_over(repos)
            snap = snapshot_bytes(index)
            us_per_doc = secs / index.N * 1e6
            rows.append({
                "repos": index.N,
                "build_s": round(secs, 3),
                "vocab": index.vocabulary_size(),
                "postings": index.total_postings(),
                "snapshot_mb": round(snap / 1e6, 2),
                "heap_peak_mb": round(peak / 1e6, 1),
                "us_per_doc": round(us_per_doc, 1),
            })
            print(f"{index.N:>8}  {secs:>8.3f}  {index.vocabulary_size():>9}  "
                  f"{index.total_postings():>10}  {snap/1e6:>11.2f}  "
                  f"{peak/1e6:>12.1f}  {us_per_doc:>10.1f}")

            # Persist the full-corpus index to the real path for downstream use.
            if n == total:
                index.save(settings.index_path)
                print(f"\nsaved full index ({index.N} docs) to {settings.index_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
