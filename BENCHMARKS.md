# Benchmarks

Measured numbers for RepoRank, captured as each milestone lands. Every figure
here comes from an actual run, not an estimate. The serving DB and index are
gitignored, so these are the record of what was built and how it performed.

## Step 1: Real corpus (crawl)

Crawled with the project's own resumable crawler (`app/ingest/crawler.py`) driven
across seven languages by `scripts/crawl_multi.py`.

Config: `stars:>=50`, star-step 25, open-ended top slice above 2000 stars, 40k
cap per language.

| Metric | Value |
|---|---|
| Total repos | 157,083 |
| Distinct topics | 105,296 |
| Star range | 68 to 451,751 |
| Repos with >=2000 stars | 7,000 |
| Star-buckets crawled (all complete) | 553 |
| Wall-clock (final run) | ~94 min |
| Crawl launches / crash-resumes | 3 launches, 2 resumes |
| Transient 5xx retries recovered (final run) | 3 |
| Rate-limit sleeps (final run) | 2 |

Per-language (from the DB, `primary_language`):

| Language | Repos |
|---|---|
| Python | 35,226 |
| JavaScript | 28,448 |
| TypeScript | 23,014 |
| Java | 19,961 |
| C++ | 19,078 |
| Go | 17,770 |
| Rust | 13,506 |
| other (GitHub language quirks) | 80 |

### What the crawl proved (and what it cost)

- **Resumability is real, not just written.** The corpus survived two mid-crawl
  crashes and resumed from `crawl_state` each time, picking up at the exact
  star-bucket that was in flight. The first crash was a transient GitHub 502; the
  second was a `full_name` unique-constraint collision (see below).
- **The retry hardening fired in production.** After the 502 crash, the crawler
  was hardened to retry transient 5xx / network errors with backoff. In the final
  run that path recovered 3 transient errors live, so the corpus completed without
  manual intervention.

### Honest caveats

- **The 1000-results-per-query cap truncates the densest low-star slices.** Each
  25-star slice returns at most 1000 repos (GitHub's hard limit), so in very dense
  ranges we capture the top 1000 of that slice. That is why the minimum star count
  in the corpus is 68 rather than 50: the `50..74` slice had more than 1000 repos
  and we kept the top of it. This is a known limitation of the Search API, not a
  crawler bug; finer slicing would recover more of the tail at the cost of more
  requests.
- **The seed corpus (30 hand-labeled repos) is deliberately NOT in this DB.** Its
  repo names collide with real repos on `full_name`, and it serves a different
  purpose (relevance evaluation). The eval harness builds its own fixture from the
  seed data, kept separate from the serving corpus.

## Step 2: Index at scale (scaling curve)

Built the inverted index over increasing prefixes of the corpus (ordered by stars
desc, so each size is a superset of the previous). Measured with
`scripts/bench_index.py`. Build time and heap peak are from `time.perf_counter`
and `tracemalloc` around the build; snapshot size is the pickled artifact on disk.

| repos | build (s) | vocab | postings | snapshot MB | heap peak MB | us/doc |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.89 | 4,869 | 17,401 | 0.54 | 9.2 | 894 |
| 5,000 | 3.00 | 13,265 | 76,401 | 2.27 | 28.3 | 600 |
| 20,000 | 10.92 | 33,459 | 263,250 | 7.74 | 85.1 | 546 |
| 50,000 | 23.95 | 62,462 | 616,777 | 17.94 | 173.7 | 479 |
| 100,000 | 41.87 | 100,280 | 1,169,232 | 33.86 | 302.3 | 419 |
| 157,083 | 46.50 | 138,113 | 1,756,590 | 50.82 | 389.7 | 296 |

Full index also loads from the snapshot in **0.60s** and serves queries.

### What the curve shows

- **Build time is roughly linear in corpus size** (~300 us/doc at steady state;
  the higher per-doc numbers at small N are fixed-cost and `tracemalloc` warmup
  amortizing out). The full 157k build takes ~46s. It is an offline batch step on
  a derived artifact, so this is not on the serving path.
- **Vocabulary grows sublinearly (Heaps' law).** Docs grow 157x from the 1k
  sample to the full corpus, but vocabulary grows only ~28x (4,869 to 138,113).
  New documents keep introducing fewer unseen terms, which is the expected shape
  for natural-language / code text.
- **Postings grow linearly**, ~11 postings per document, to 1.76M total.
- **The index fits in memory comfortably.** The persisted snapshot is 51 MB; the
  `tracemalloc` heap peak of ~390 MB is the *build-time* peak (it includes
  transient allocations and overstates the resident index). This validates the
  in-memory design with real numbers: no sharding is needed at this scale.

### Versus the 30-doc baseline

The original demo corpus was 30 docs / 238 vocab / 427 postings / 0.011s build.
The real corpus is ~5,200x the documents, ~580x the vocabulary (sublinear, as
expected), ~4,100x the postings, and ~4,200x the build time. Every earlier number
in the README that described the 30-doc toy has been replaced with these.

### Lead-in to step 3

Serving latency is not uniform. A tight query like `distributed systems` (2,391
matches) returns its top page in ~8 ms, but a broad multi-term query like
`react state management` (11,250 matches) takes ~176 ms because every matching
doc is scored term-at-a-time and then min-max normalized. That tail is exactly
what the step 3 latency harness and result cache target.

## Step 3: Latency under load + result cache

Load-tested the engine over the full 157k-repo index with `scripts/bench_latency.py`.
Closed-loop: C worker threads issue queries back-to-back for 5s per level.

**Workload (this determines the hit-rate, so it is stated in full).** A fixed pool
of **400 distinct** queries, each a 1-3 term combination drawn from a 30-term
vocabulary, generated once with a fixed seed. During the run each worker samples
the pool with a **Zipf (1/rank) weighting**, so a small head of queries recurs
often and a long tail is comparatively cold, which is the shape real search
traffic takes. The cache is an **LRU with capacity 256**, deliberately smaller
than the 400-query working set so eviction actually happens (the tail evicts
itself; the head stays resident).

**Cache OFF** (`cache_size=0`):

| concurrency | QPS | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 100 | 7.3 | 23.8 | 64.3 |
| 2 | 112 | 12.8 | 46.6 | 84.8 |
| 4 | 91 | 33.5 | 114.1 | 161.2 |
| 8 | 91 | 63.9 | 230.4 | 322.6 |
| 16 | 91 | 102.6 | 493.6 | 642.2 |
| 32 | 100 | 96.9 | 614.1 | 1120.2 |

**Cache ON** (LRU, capacity 256, measured hit-rate **94.3%** on the Zipfian
workload above). The 94.3% is a property of that query distribution, not of the
system: a uniform-random or higher-cardinality stream would hit far less, and a
stream with no repeats would hit ~0%. The number is meaningful only next to the
workload that produced it.

| concurrency | QPS | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|
| 1 | 1526 | <0.1 | 3.4 | 16.4 |
| 2 | 2021 | <0.1 | <0.1 | 28.7 |
| 4 | 1830 | <0.1 | <0.1 | 69.4 |
| 8 | 1399 | <0.1 | 3.3 | 167.4 |
| 16 | 1091 | <0.1 | 49.5 | 360.6 |
| 32 | 874 | <0.1 | 126.2 | 614.1 |

### What the numbers say

- **Throughput saturates almost immediately without the cache.** A single Python
  process scoring BM25 term-at-a-time tops out at ~90-110 QPS, and it stays there
  no matter how many threads pile on, because the GIL serializes the CPU-bound
  scoring. Extra concurrency buys only queueing: p95 goes from 24 ms at C=1 to
  614 ms at C=32, and p99 reaches 1.1 s. That is the degradation point.
- **The cache lifts effective throughput ~15-20x** on this Zipfian workload
  (100 to ~1500-2000 QPS) because a 94% hit is a dict lookup measured in
  microseconds, so the median request is served in under 0.1 ms.
- **The cache is not a free lunch, and the data shows where it stops helping.**
  Cache-on throughput peaks around C=2 (~2000 QPS) and then *declines* to ~874 QPS
  at C=32: the 5.7% cold misses are still GIL-bound, and piling on threads adds
  lock and scheduler contention around those misses. The miss tail is why p99
  climbs back to 360-614 ms at high concurrency even with the cache on.
- **Honest takeaway.** The cache is the right first move (it removes the head of
  the traffic from the hot path for almost nothing), but the ceiling past it is
  the single-process GIL. The next lever is multi-process workers (each with its
  own in-memory index) or moving the inner scoring loop out of pure Python, not a
  bigger cache.

### Profiling: is it really the GIL? (not inferred from the curve)

The "GIL-bound" claim is backed by `scripts/profile_search.py`, not by the shape
of the throughput curve. Three checks:

1. **The search path does no I/O.** An audit of `engine.py` finds no DB session,
   socket, or file access; the harness drives `SearchEngine.search` directly, with
   no FastAPI and no SQLAlchemy session. So SQLite write serialization cannot be
   in the measured path (DB hydration and the search-log INSERT happen in the API
   layer, which this benchmark does not exercise). The reload lock is likewise not
   in the path: no reload runs during a load level, and the swap is off to the
   side (see `app/api/state.py`).
2. **cProfile puts the time in pure-Python scoring.** Over 300 cold-miss searches,
   cumulative time is dominated by `search` (the candidate loop), `score_terms`,
   `_passes_filters` (~2M calls), `_recency_decay`, list `sort`, and `_normalize`,
   plus `sum` / `max` / `math.log` builtins. No lock-acquire and no I/O frames
   appear.
3. **The same work parallelizes across processes but not threads.** Identical
   CPU-bound query batch, pools warmed so spawn / index-load is excluded from the
   timing:

   | workers | threads | processes |
   |---:|---:|---:|
   | 1 (baseline) | 75 qps | 75 qps |
   | 2 | 76 qps (1.01x) | 120 qps (1.59x) |
   | 4 | 75 qps (0.99x) | 145 qps (1.93x) |

   Threads add zero throughput (the GIL serializes them); processes scale
   (independent interpreters, so no shared GIL). Process scaling is sub-linear
   because of IPC and core limits, but the qualitative split (flat threads vs.
   scaling processes) is the direct fingerprint of a GIL-bound, CPU-bound service.

## Step 4: Ranking evaluation as a CI gate

The eval scores each ranker against a **frozen snapshot of the full 157k-repo
index** (`eval_index.pkl`, built by `python -m app.cli freeze-eval`) with all 27
labeled repos embedded, so the ranker has to surface the labels past ~157k real
distractors. Judgments are keyed on repo full_name (`app/eval/qrels.py`); the
freeze resolves them to doc_ids and writes `frozen_qrels.json` and `baseline.json`
so the gate is reproducible and independent of the live DB.

**Labels (27 across 10 queries) are guaranteed present in the corpus:**
22 are real repos (already crawled, or live-fetched from the GitHub API for ones
whose language was outside the crawl, e.g. `redis/redis` and `valkey-io/valkey`
are C), and 5 are synthetic seed repos (tutorials / starters that were never real
GitHub repos) injected from the seed data. Two real repos (`facebook/react`,
`tiangolo/fastapi`) needed a redirect followed because GitHub 301s transferred
repos; their real stats are kept and identity pinned to the label.

**Results on the full corpus (nDCG@10, bootstrap 95% CI over the 10 queries):**

| ranker | nDCG@10 | 95% CI | MRR | P@5 |
|---|---:|:--:|---:|---:|
| popularity_heavy | 0.513 | [0.385, 0.662] | 0.625 | 0.320 |
| bm25f_v1 | 0.424 | [0.281, 0.595] | 0.650 | 0.260 |
| bm25_v1 | 0.340 | [0.191, 0.522] | 0.587 | 0.220 |
| bm25_only | 0.183 | [0.057, 0.335] | 0.326 | 0.100 |

### What this shows (and why it matters more than the old numbers)

- **At scale the ranking story inverts.** On the old 30-doc corpus every ranker
  scored ~0.95-0.98 and pure BM25 nominally "won"; the corpus was too small for
  the number to mean anything. Against 157k distractors, pure BM25 **collapses to
  0.183**: for a query like `react frontend library` the canonical `facebook/react`
  is only rank 2 under pure lexical scoring (a shorter exact-match repo beats it),
  and the second labeled repo falls out of the top 10 entirely. Popularity
  blending pulls `facebook/react` to rank 1 and lifts nDCG to 0.513. This is the
  measured case for the blended ranker, which the toy corpus could not make.
- **The top two rankers are a statistical tie, and the shipped default is
  bm25f_v1.** popularity_heavy's point estimate (0.513) is nominally above
  bm25f_v1's (0.424), but at n=10 the bootstrap CIs overlap heavily
  ([0.385, 0.662] vs [0.281, 0.595]), so the difference is not distinguishable from
  noise: it is a tie, not a lead. The tie breaks on robustness, not on the point
  estimate. Per query, popularity_heavy is actually **worse than bm25f_v1 on 5 of
  the 10 queries**; its aggregate comes entirely from head queries where the
  relevant repos happen to be the most-starred (in memory key value store: 0.613
  vs 0.252; monitoring and metrics: 0.850 vs 0.387). On specific / tail queries it
  fails by sorting popular-but-off-topic repos to the top: **raft consensus
  algorithm scores 0.333 for popularity_heavy vs 0.527 for bm25f_v1**, because the
  on-topic repo (`tikv/raft-rs`) is not a mega-star and an 0.8 star weight buries
  it. bm25f_v1 is content-driven and is the field-weighting this project exists to
  demonstrate, so it ships; popularity_heavy stays in the eval as a documented
  comparison, with that failure mode recorded as the reason it is not shipped
  despite the higher point estimate.

### The gate, and why it is built the way it is

`python -m app.cli eval-gate` (and `tests/test_gate.py`) fail the build if the
shipped ranker's nDCG@10 falls more than **0.05** below the committed baseline.

- **Gate on the point estimate, not the CI.** The bootstrap 95% CIs above are wide
  (e.g. bm25f_v1 spans [0.281, 0.595]) because n=10 is small. Gating on a CI bound
  would flap on noise. So the gate uses the point estimate with a fixed margin, and
  the n=10 coarseness is stated rather than hidden. The CIs are still reported so
  the noise is visible.
- **Reproducible, and enforced in cloud CI.** The frozen index is 51 MB and
  gitignored, so it ships as a GitHub release asset (`eval-index-v1`). The CI
  workflow downloads that exact file before running the suite, so the gate enforces
  in GitHub Actions against the identical snapshot the baseline was computed on
  (`frozen_qrels.json` and `baseline.json` are committed for review). The gate
  test skips-green only if the asset is ever unavailable, so CI never breaks on a
  missing artifact.

### Two limitations of this eval, stated plainly

Neither is smoothed over; both are real and bound how far these numbers should be
pushed.

- **n=10 queries: the top two rankers are statistically indistinguishable.** The
  bootstrap 95% CIs overlap heavily (popularity_heavy [0.385, 0.662] vs bm25f_v1
  [0.281, 0.595]). The 0.09 point-estimate gap is within noise, which is precisely
  why the gate is on the point estimate with a margin and not on a CI bound.
- **Shallow pools depress and can bias the scores.** Only ~27 repos across the 10
  queries are judged, so most of each ranker's top-10 is unjudged and counted as
  non-relevant by nDCG@10. That drags every score down in absolute terms and can
  bias the between-ranker comparison, since a ranker that surfaces genuinely
  relevant but unjudged repos is penalized for it. These numbers are sound for
  regression detection and relative comparison, not as absolute relevance.

The **highest-leverage next eval step is pooling**, not more queries: take the
union of each ranker's top-k per query, judge that pool, and re-score. That
directly removes the unjudged-as-non-relevant bias, and it is far cheaper than
expanding the query set, so it comes first.
