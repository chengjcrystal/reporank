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
  current scale (tens of thousands of repos) it fits comfortably in RAM; sharding
  is discussed but unnecessary.
- **Blended ranking is the differentiator.** Pure BM25 ignores quality, so the
  final score blends text relevance + popularity + recency:
  `final = w_text·norm(bm25) + w_pop·norm(log(stars+1)) + w_fresh·recency_decay`.
  Weights are chosen by a `ranker` query param so ranking variants can be A/B'd.
- **No stemming in v1** — it mangles tech terms ("redis" → "redi"). Planned as a
  measurable experiment behind a flag.

## Tech stack

Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite (default, zero-setup) or Postgres
(via docker-compose), httpx (crawler), pytest. Vanilla-JS single-page frontend
served by FastAPI. No external search engine.

## Repository layout

```
github-search/
  app/
    config.py                 # env/settings
    db.py                     # SQLAlchemy engine/session (SQLite or Postgres)
    models.py                 # Repository, Topic, CrawlState, SearchLog
    schemas.py                # Pydantic API response models
    main.py                   # FastAPI app, serves frontend + API, loads index
    cli.py                    # pipeline CLI: init-db | seed | crawl | build-index | stats
    ingest/
      crawler.py              # GitHub API crawler: star-slicing, rate limits, resumable
      normalize.py            # raw API repo -> DB rows; builds search_document
      seed_data.py            # 30 curated demo repos (offline demo without a token)
    search/
      tokenizer.py            # tech-aware tokenizer (keeps c++, node.js), stopwords
      index.py                # InvertedIndex: postings, doc stats, save/load snapshot
      bm25.py                 # BM25 scoring from scratch (term-at-a-time)
      engine.py               # filters + blended ranking + pagination; ranker variants
      builder.py              # builds the index from the DB
    api/
      routes.py               # /api/search, /repos/{id}, /similar, /suggest, /filters, /stats, click
      state.py                # in-memory engine holder, snapshot reload
  web/                        # index.html, app.js, styles.css (dark GitHub-style SPA)
  tests/                      # test_tokenizer.py, test_bm25.py, test_engine.py (15 tests)
  requirements.txt  docker-compose.yml  README.md  .env.example
```

## What is BUILT and verified working

- Crawler with the 1000-result-cap workaround (star-range slicing), rate-limit
  handling, and `crawl_state` resumability.
- Full DB schema + idempotent upsert pipeline.
- Tech-aware tokenizer; inverted index with persistence; BM25 from scratch.
- Blended ranker with 3 variants (`bm25_only`, `bm25_v1`, `popularity_heavy`).
- All four filters: language, min_stars, topics (AND), updated_after.
- REST API + auto OpenAPI docs at /docs.
- Frontend SPA: search box w/ autocomplete, filter sidebar, result cards with
  score + latency badge, pagination, analytics panel.
- Click logging + analytics endpoint (top queries, CTR, p50/p95 latency).
- 15 passing tests; BM25 validated against an independent reference implementation.

Verified demos: "distributed systems projects" returns etcd/prometheus/k8s;
`redis` under `bm25_only` → a build-your-own-redis tutorial (pure relevance) vs
`popularity_heavy` → redis/redis; "similar to Redis" → valkey + dragonfly.

## What is NOT yet built (roadmap / next phases)

- Semantic search via embeddings + pgvector (hybrid BM25 + cosine).
- BM25F field weighting (name ≫ description ≫ README).
- Typo tolerance (trigram / edit distance).
- Redis result cache.
- nDCG / MRR evaluation on a hand-labeled query set (hard relevance metrics).
- Alembic migrations (currently uses create_all).

## How to run it

```bash
cd github-search
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.cli seed          # load 30 demo repos (no token needed)
python -m app.cli build-index   # build + save the inverted index
uvicorn app.main:app --reload   # http://localhost:8000 ; API docs at /docs
```

Crawl real data: put `GITHUB_TOKEN=...` in `.env`, then
`python -m app.cli crawl --language python --min-stars 100 --max-repos 2000`
followed by `python -m app.cli build-index`.

## Resume metrics to track

Scale (repos indexed, vocabulary size, index build time), performance (search
p50/p95 latency, queries/sec), quality (CTR, nDCG comparing ranker variants,
zero-result rate). The `/api/stats` endpoint already surfaces several of these.
