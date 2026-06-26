# RepoRank — GitHub Repository Search Engine

A search engine for GitHub repositories with a **custom inverted index** and
**BM25 ranking implemented from scratch** (no Elasticsearch / Algolia), plus a
quality-aware blended ranker that combines text relevance with popularity and
recency to surface better projects than GitHub's default search.

```
distributed systems projects   ·   FastAPI PostgreSQL applications
computer vision with deployment ·   projects similar to Redis
```

## Architecture

```
GitHub API ──▶ Crawler ──▶ PostgreSQL (source of truth) ──▶ Indexer ──▶ snapshot.pkl
 (rate-limit,   (resumable    repositories / topics /         (tokenize,    (in-memory
  star-slice)    crawl_state)  search_logs)                    inverted      inverted
                                                               index)        index)
                                                                                │
                            React-ish SPA  ◀──  FastAPI  ◀── BM25 + filters + blended re-rank
```

The **ingestion** path (offline batch) is cleanly separated from the **serving**
path (online, in-memory, low-latency). The search index is a *derived artifact*:
it can always be rebuilt from Postgres.

## Quickstart (zero setup — uses SQLite + seed data)

```bash
cd github-search
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m app.cli seed          # load a curated demo dataset
python -m app.cli build-index   # build + persist the inverted index
uvicorn app.main:app --reload   # open http://localhost:8000
```

Then open **http://localhost:8000** and try `distributed systems projects` or
`FastAPI PostgreSQL`. API docs are auto-generated at **/docs**.

## Crawl real data

```bash
echo "GITHUB_TOKEN=ghp_xxx" >> .env       # 60 -> 5000 req/hr
python -m app.cli crawl --language python --min-stars 100 --max-repos 2000
python -m app.cli build-index
```

The crawler beats GitHub's 1000-results-per-query cap by **slicing the corpus
into star-range buckets**, and respects rate limits via the response headers.
Progress is checkpointed in `crawl_state`, so it resumes after a crash.

## Use Postgres instead of SQLite

```bash
docker compose up -d db
pip install "psycopg[binary]"
# in .env:  DATABASE_URL=postgresql+psycopg://ghsearch:ghsearch@localhost:5432/ghsearch
```

## Search internals

- **Tokenizer** (`app/search/tokenizer.py`) — lowercase, tech-aware (keeps `c++`,
  `node.js`), curated stopwords, identical for indexing and querying.
- **Inverted index** (`app/search/index.py`) — `term → [(doc_id, tf)]`, doc
  lengths, corpus stats; persisted as a snapshot, loaded into RAM.
- **BM25** (`app/search/bm25.py`) — term-at-a-time scoring, from scratch.
- **Blended ranker** (`app/search/engine.py`) —
  `final = w_text·bm25 + w_pop·log(stars) + w_fresh·recency`, selectable via the
  `ranker` query param for A/B experiments (`bm25_only`, `bm25_v1`, `popularity_heavy`).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/search` | ranked search w/ filters (language, min_stars, topics, updated_after), pagination, latency |
| `GET /api/repos/{id}` | repository detail |
| `GET /api/repos/{id}/similar` | content similarity (topic Jaccard) |
| `GET /api/suggest` | autocomplete |
| `GET /api/filters` | facet values for the UI |
| `POST /api/events/click` | click logging for CTR |
| `GET /api/stats` | analytics: top queries, CTR, p50/p95 latency |

## Tests

```bash
pytest -q
```

BM25 is validated against an independent reference implementation on a hand-built
corpus; the tokenizer and engine (filters, blended ranking) have unit tests too.

## Roadmap

- Semantic search via embeddings + pgvector (hybrid BM25 + cosine)
- BM25F field weighting (name ≫ description ≫ README)
- Typo tolerance (trigram / edit distance)
- Redis result cache; nDCG evaluation on a labeled query set
