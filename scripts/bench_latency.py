"""Load-test the search engine and measure latency percentiles vs throughput.

Method
------
- Workload: a fixed pool of realistic 1-3 term queries over the corpus, sampled
  with a Zipfian skew so a head of popular queries recurs (like real traffic) and
  a long tail is comparatively cold. The pool is larger than the cache so the
  cache genuinely evicts.
- Closed-loop load: for each concurrency level C, C worker threads issue queries
  back-to-back for a fixed duration. Achieved QPS = calls / elapsed; latency
  percentiles are over every call. (Search scoring is CPU-bound Python, so this
  mirrors a single uvicorn worker under the GIL: concurrency exposes queueing.)
- Two passes: cache OFF (cache_size=0) and cache ON, so the delta is isolated.

Run from the repo root:
    .venv/bin/python scripts/bench_latency.py
"""
from __future__ import annotations

import random
import threading
import time

from app.search.engine import SearchEngine
from app.search.index import InvertedIndex

INDEX_PATH = "./index_snapshot.pkl"
CONCURRENCY = [1, 2, 4, 8, 16, 32]
DURATION_S = 5.0
CACHE_CAPACITY = 256
POOL_SIZE = 400
SEED = 1234

# Real terms that occur across the corpus, combined into queries.
TERMS = [
    "python", "javascript", "react", "api", "database", "cache", "async",
    "cli", "docker", "kubernetes", "machine", "learning", "web", "framework",
    "server", "client", "testing", "parser", "compiler", "game", "bot",
    "http", "json", "graphql", "orm", "queue", "stream", "vector", "search",
    "distributed", "systems", "rust", "golang", "typescript", "microservice",
    "auth", "encryption", "scraper", "dashboard", "analytics", "neural",
    "network", "image", "audio", "terminal", "editor", "markdown", "static",
]


def build_pool(rng: random.Random) -> list[str]:
    pool = []
    for _ in range(POOL_SIZE):
        k = rng.choice([1, 1, 2, 2, 2, 3])  # mostly 1-2 term queries
        pool.append(" ".join(rng.sample(TERMS, k)))
    return pool


def zipf_indices(rng: random.Random, n: int):
    """Infinite generator of pool indices with a Zipf-like 1/rank weighting."""
    weights = [1.0 / (i + 1) for i in range(n)]
    order = list(range(n))
    rng.shuffle(order)  # decouple popularity from pool position
    while True:
        yield rng.choices(order, weights=weights, k=1)[0]


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(p * len(sorted_vals)))
    return sorted_vals[idx]


def run_level(engine: SearchEngine, pool: list[str], concurrency: int,
              duration: float) -> dict:
    stop_at = time.perf_counter() + duration
    lat_lists: list[list[float]] = [[] for _ in range(concurrency)]

    def worker(slot: int):
        rng = random.Random(SEED + slot)
        picker = zipf_indices(rng, len(pool))
        lats = lat_lists[slot]
        while time.perf_counter() < stop_at:
            q = pool[next(picker)]
            t0 = time.perf_counter()
            engine.search(q, per_page=20)
            lats.append((time.perf_counter() - t0) * 1000.0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    lats = sorted(l for sub in lat_lists for l in sub)
    calls = len(lats)
    return {
        "concurrency": concurrency,
        "calls": calls,
        "qps": round(calls / elapsed, 1),
        "p50": round(percentile(lats, 0.50), 1),
        "p95": round(percentile(lats, 0.95), 1),
        "p99": round(percentile(lats, 0.99), 1),
    }


def sweep(label: str, cache_size: int, pool: list[str]) -> list[dict]:
    print(f"\n=== {label} (cache_size={cache_size}) ===")
    index = InvertedIndex.load(INDEX_PATH)
    engine = SearchEngine(index, cache_size=cache_size)
    print(f"{'conc':>5} {'calls':>8} {'qps':>9} {'p50_ms':>8} {'p95_ms':>8} {'p99_ms':>8}")
    rows = []
    for c in CONCURRENCY:
        r = run_level(engine, pool, c, DURATION_S)
        rows.append(r)
        print(f"{r['concurrency']:>5} {r['calls']:>8} {r['qps']:>9} "
              f"{r['p50']:>8} {r['p95']:>8} {r['p99']:>8}")
    if engine.cache is not None:
        print("cache:", engine.cache.stats())
        rows_hit = engine.cache.stats()["hit_rate"]
        for r in rows:
            r["hit_rate"] = rows_hit
    return rows


def main() -> None:
    rng = random.Random(SEED)
    pool = build_pool(rng)
    print(f"workload: {len(pool)} distinct queries, Zipf-sampled, "
          f"cache capacity {CACHE_CAPACITY}, {DURATION_S}s per level")
    off = sweep("CACHE OFF", 0, pool)
    on = sweep("CACHE ON", CACHE_CAPACITY, pool)

    print("\n=== delta (cache on vs off) ===")
    print(f"{'conc':>5} {'qps_off':>8} {'qps_on':>8} {'p50_off':>8} {'p50_on':>8} "
          f"{'p95_off':>8} {'p95_on':>8}")
    for a, b in zip(off, on):
        print(f"{a['concurrency']:>5} {a['qps']:>8} {b['qps']:>8} "
              f"{a['p50']:>8} {b['p50']:>8} {a['p95']:>8} {b['p95']:>8}")


if __name__ == "__main__":
    main()
