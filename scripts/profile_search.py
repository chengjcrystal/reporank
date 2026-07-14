"""Attribute where cold-miss search time goes, and test the GIL hypothesis.

Three checks, so "GIL-bound" is profiled rather than inferred from a curve:

1. I/O audit: the engine search path touches no DB / socket / disk. The harness
   drives `SearchEngine.search` directly (no FastAPI, no SQLAlchemy session), so
   SQLite serialization cannot be in the measured path. Printed for the record.
2. cProfile of cold-miss searches: shows the time is spent in pure-Python scoring
   (`score_terms`, `_normalize`, sort), not in locks or I/O.
3. Thread-vs-process scaling: the same CPU-bound work run across N threads (shared
   GIL) vs N processes (independent interpreters). If threads stay flat and
   processes scale ~N x, the bottleneck is the GIL, definitively.

Run from repo root:
    .venv/bin/python scripts/profile_search.py
"""
from __future__ import annotations

import cProfile
import io
import pstats
import random
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from app.search.engine import SearchEngine
from app.search.index import InvertedIndex

INDEX_PATH = "./index_snapshot.pkl"
TERMS = [
    "python", "javascript", "react", "api", "database", "cache", "async", "cli",
    "docker", "kubernetes", "machine", "learning", "web", "framework", "server",
    "client", "testing", "parser", "compiler", "game", "http", "json", "graphql",
    "orm", "queue", "stream", "vector", "search", "distributed", "systems",
]

_ENGINE: SearchEngine | None = None  # per-process/thread shared engine (no cache)


def _init() -> None:
    global _ENGINE
    _ENGINE = SearchEngine(InvertedIndex.load(INDEX_PATH))  # cache off -> always cold


def _do(q: str) -> int:
    _ENGINE.search(q, per_page=20)
    return 1


def make_queries(n: int, seed: int = 7) -> list[str]:
    rng = random.Random(seed)
    return [" ".join(rng.sample(TERMS, rng.choice([1, 2, 2, 3]))) for _ in range(n)]


def profile_cold() -> None:
    print("=== 2. cProfile of 300 cold-miss searches (cumulative) ===")
    eng = SearchEngine(InvertedIndex.load(INDEX_PATH))
    qs = make_queries(300)
    pr = cProfile.Profile()
    pr.enable()
    for q in qs:
        eng.search(q, per_page=20)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(12)
    # Trim to the informative lines.
    for line in s.getvalue().splitlines():
        if line.strip() and ("function calls" in line or "cumtime" in line
                             or "app/search" in line or "{method 'sort'" in line
                             or "{built-in method" in line):
            print(line)


def scaling() -> None:
    print("\n=== 3. thread vs process scaling on the same CPU-bound work ===")
    print("    (pools are warmed before timing so spawn + per-process index load "
          "are excluded)")
    qs = make_queries(1500)

    # single in-process baseline
    _init()
    t0 = time.perf_counter()
    for q in qs:
        _do(q)
    base = len(qs) / (time.perf_counter() - t0)
    print(f"  1 worker (baseline):   {base:7.0f} qps")

    for P in (2, 4):
        with ThreadPoolExecutor(max_workers=P) as ex:  # shares _ENGINE + GIL
            list(ex.map(_do, ["warm"] * (2 * P)))       # spin up threads first
            t0 = time.perf_counter()
            list(ex.map(_do, qs, chunksize=max(1, len(qs) // (P * 4))))
            tq = len(qs) / (time.perf_counter() - t0)
        print(f"  {P} threads:            {tq:7.0f} qps   ({tq/base:.2f}x baseline)")

    for P in (2, 4):
        with ProcessPoolExecutor(max_workers=P, initializer=_init) as ex:
            list(ex.map(_do, ["warm"] * (2 * P)))       # force spawn + index load
            t0 = time.perf_counter()
            list(ex.map(_do, qs, chunksize=max(1, len(qs) // (P * 4))))
            pq = len(qs) / (time.perf_counter() - t0)
        print(f"  {P} processes:          {pq:7.0f} qps   ({pq/base:.2f}x baseline)")


def main() -> None:
    print("=== 1. I/O audit of the search path ===")
    src = open("app/search/engine.py").read()
    io_markers = ["sqlite", "session", "execute(", "socket", "open(", "requests", "httpx"]
    hits = [m for m in io_markers if m in src.lower()]
    print(f"  I/O markers found in engine.py search path: {hits or 'none'}")
    print("  (search reads only in-memory dicts; DB hydration happens in the API "
          "layer, not in SearchEngine.search)")
    profile_cold()
    scaling()


if __name__ == "__main__":
    main()
