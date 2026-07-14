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
