# Project Context — RepoRank (GitHub Repository Search Engine)

> Paste/upload this file into a Claude.ai Project or new chat to bring Claude
> fully up to speed on what this project is and what has been built so far.

## What this project is

A portfolio project for SWE internship applications (Berkeley EECS student).
A **GitHub repository search engine** that ranks results better than GitHub's
default search. The point is to demonstrate backend engineering, database
design, information retrieval, a custom inverted index, BM25 ranking from
scratch, ranking experiments, and clean system design — WITHOUT relying on
Elasticsearch / Algolia / managed search.

Example queries it handles: "distributed systems projects",
"FastAPI PostgreSQL applications", "computer vision with deployment",
"projects similar to Redis", "beginner-friendly backend projects".

## Key design decisions (and the reasoning, for interviews)

- **Postgres is the source of truth; the search index is a derived artifact.**
  The inverted index can always be rebuilt from the DB. This clean separation of
  the offline ingestion path from the online serving path is the core system-
  design idea.
- **Build the IR core by hand, but use Postgres for storage** — demonstrates both
  understanding of search internals and pragmatic infra choices.
- **In-memory inverted index** loaded from a disk snapshot at API startup. At the
  real corpus scale (157,083 repos, a 51 MB snapshot that loads in 0.6 s) it fits
  comfortably in RAM; sharding is discussed but unnecessary.
- **Blended ranking is the differentiator.** Pure BM25 ignores quality, so the
  final score blends text relevance + popularity + recency:
  `final = w_text·norm(bm25) + w_pop·norm(log(stars+1)) + w_fresh·recency_decay`.
  Weights are chosen by a `ranker` query param so ranking variants can be A/B'd.
- **No stemming in v1** — it mangles tech terms ("redis" → "redi"). Planned as a
  measurable experiment behind a flag.

## Tech stack

Python 3.13, FastAPI, SQLAlchemy 2.0, SQLite (default, zero-setup) or Postgres
(via docker-compose), httpx (crawler), pytest. Vanilla-JS single-page frontend
served by FastAPI. In-process LRU result cache (no Redis). No external search
engine. CI runs the full suite plus a ranking-regression gate on every push.

## Repository layout

```
reporank/
  app/
    config.py                 # env/settings (index paths, cache_size)
    db.py                     # SQLAlchemy engine/session (SQLite or Postgres)
    models.py                 # Repository, Topic, CrawlState, SearchLog
    schemas.py                # Pydantic API response models
    main.py                   # FastAPI app, serves frontend + API, loads index
    cli.py                    # seed | crawl | build-index | evaluate | freeze-eval | eval-gate
    ingest/
      crawler.py              # GitHub crawler: star-slicing, rate limits, 5xx retry, resumable
      normalize.py            # raw API repo -> DB rows; builds search_document
      seed_data.py            # 30 seed repos: offline demo + source for eval labels
    search/
      tokenizer.py            # tech-aware tokenizer (keeps c++, node.js), stopwords
      index.py                # InvertedIndex: postings, doc stats, save/load snapshot
      bm25.py                 # BM25 scoring from scratch (term-at-a-time)
      bm25f.py                # BM25F field-weighted scoring from scratch
      cache.py                # thread-safe LRU result cache
      engine.py               # filters + blended ranking + cache; ranker variants
      builder.py              # builds the index from the DB
    eval/
      qrels.py                # hand-labeled judgments, keyed on full_name
      metrics.py              # nDCG / MRR / P@k from scratch
      labels.py               # resolve labels against corpus; fetch/inject missing
      gate.py                 # bootstrap CI + freeze + ranking-regression gate
      evaluate.py             # score every ranker on the frozen index
    api/
      routes.py               # /api/search, /repos/{id}, /similar, /suggest, /filters, /stats, click
      state.py                # in-memory engine holder, atomic snapshot reload
  scripts/                    # crawl_multi.py, bench_index.py, bench_latency.py, profile_search.py
  web/                        # index.html, app.js, styles.css (dark GitHub-style SPA)
  tests/                      # 49 tests across tokenizer/bm25/bm25f/engine/cache/eval/gate/crawler
  .github/workflows/ci.yml    # runs tests + the ranking gate against the frozen index
  BENCHMARKS.md               # measured numbers per milestone (crawl, scale, latency, eval)
  requirements.txt  docker-compose.yml  README.md  .env.example
```

## What is BUILT and verified working

- Crawler with the 1000-result-cap workaround (star-range slicing), rate-limit
  handling, and `crawl_state` resumability.
- Full DB schema + idempotent upsert pipeline.
- Tech-aware tokenizer; field-aware inverted index with persistence; BM25 from scratch.
- BM25F field weighting from scratch: the index stores per-field term frequencies
  (name / description / topics / readme) so a name match outranks a README match;
  reduces exactly to BM25 on a single field. Exposed as the `bm25f_v1` variant.
- Blended ranker with 4 variants (`bm25_only`, `bm25_v1`, `popularity_heavy`,
  `bm25f_v1`).
- All four filters: language, min_stars, topics (AND), updated_after.
- REST API + auto OpenAPI docs at /docs.
- Frontend SPA: search box w/ autocomplete, filter sidebar, result cards with
  score + latency badge, pagination, analytics panel.
- Click logging + analytics endpoint (top queries, CTR, p50/p95 latency).
- Real 157k-repo corpus crawled across 7 languages, surviving two mid-crawl
  crashes via `crawl_state` resume (see BENCHMARKS.md step 1).
- Index scaling curve (1k to 157k): linear build (~300 us/doc), sublinear vocab
  (Heaps' law), 51 MB snapshot (step 2).
- Latency harness + in-process LRU cache: single process saturates ~100 QPS
  (profiled GIL-bound), cache lifts effective throughput ~15-20x on Zipfian
  traffic at a 94% hit-rate (step 3).
- Offline evaluation as a CI gate: judgments keyed on full_name, scored against a
  frozen snapshot of the full 157k index with the labeled repos embedded, so the
  ranker must surface them past ~157k distractors. nDCG / MRR / P@k from scratch,
  bootstrap CIs, and a point-estimate gate that fails the build on regression
  (step 4).
- 49 passing tests; BM25 / BM25F and the ranking metrics each validated against
  independent / hand-computed reference values.

Evaluation results (10 labeled queries, full 157k frozen index, fixed clock):

| ranker           | nDCG@10 | 95% CI          |  MRR  |  P@5  |
|------------------|---------|-----------------|-------|-------|
| popularity_heavy |  0.513  | [0.385, 0.662]  | 0.625 | 0.320 |
| bm25f_v1 (shipped) | 0.424 | [0.281, 0.595]  | 0.650 | 0.260 |
| bm25_v1          |  0.340  | [0.191, 0.522]  | 0.587 | 0.220 |
| bm25_only        |  0.183  | [0.057, 0.335]  | 0.326 | 0.100 |

Reading: against 157k distractors the story inverts from the old 30-doc toy (where
everything scored ~0.97). Pure BM25 collapses (0.183) as exact-lexical distractors
bury the canonical repos; blending in quality signal is what surfaces them.
popularity_heavy's nominal lead over bm25f_v1 is within the overlapping CIs at
n=10 (a statistical tie), and it fails on specific / tail queries (raft consensus
algorithm: 0.333 vs 0.527) by over-weighting stars, so the content-driven bm25f_v1
ships. Two eval caveats are stated openly: n=10 makes the CIs wide (hence the
point-estimate gate), and shallow pools (~27 labels) score unjudged repos as
non-relevant, depressing absolute numbers.

## What is NOT yet built (roadmap / next phases)

- Pooling for the eval (union each ranker's top-k, judge, re-score): highest-
  leverage next step, removes the shallow-pool bias before expanding queries.
- Multi-process serving workers to lift the single-process GIL throughput ceiling.
- Semantic search via embeddings + pgvector (hybrid BM25 + cosine).
- Typo tolerance (trigram / edit distance).
- Shared / cross-process result cache (current cache is in-process LRU).
- Alembic migrations (currently uses create_all).

## How to run it

```bash
cd reporank
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli seed          # load 30 demo repos (no token needed)
python -m app.cli build-index   # build + save the inverted index
uvicorn app.main:app --reload   # http://localhost:8000 ; API docs at /docs
python -m app.cli freeze-eval   # inject labels, freeze the eval index, write baseline
python -m app.cli eval-gate     # fail if the shipped ranker regressed
```

Crawl real data: put `GITHUB_TOKEN=...` in `.env`, then
`python -m app.cli crawl --language python --min-stars 100 --max-repos 2000`
followed by `python -m app.cli build-index`.

## Resume metrics to track

Scale (repos indexed, vocabulary size, index build time), performance (search
p50/p95 latency, queries/sec), quality (CTR, nDCG comparing ranker variants,
zero-result rate). The `/api/stats` endpoint already surfaces several of these.
