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
# or crawl many languages at once:
python scripts/crawl_multi.py
```

The crawler beats GitHub's 1000-results-per-query cap by **slicing the corpus
into star-range buckets**, respects rate limits via the response headers, and
retries transient 5xx / network errors with backoff. Progress is checkpointed in
`crawl_state`, so it resumes from the exact in-flight bucket after a crash.

This was run for real: a 7-language crawl (Python, JavaScript, TypeScript, Go,
Rust, Java, C++) landed **157,083 repositories** in ~94 min, surviving two
mid-crawl crashes (a transient GitHub 502 and a data collision) by resuming from
`crawl_state` each time. Full numbers and caveats are in
[BENCHMARKS.md](BENCHMARKS.md).

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

## Scale

Measured on the real **157,083-repo** corpus (`scripts/bench_index.py`):

| repos | index build | vocab | postings | snapshot | load |
|---:|---:|---:|---:|---:|---:|
| 157,083 | ~46 s | 138,113 | 1,756,590 | 51 MB | 0.60 s |

Build time is linear in corpus size (~300 us/doc); vocabulary grows sublinearly
(Heaps' law). The whole index is 51 MB on disk and loads into RAM in under a
second, which is why the in-memory design needs no sharding at this scale. The
full scaling curve (1k to 157k) is in [BENCHMARKS.md](BENCHMARKS.md).

**Serving latency + cache.** Load-tested over the full corpus
(`scripts/bench_latency.py`), a single process scoring BM25 term-at-a-time
saturates at ~100 QPS and its tail latency balloons under concurrency (p99 1.1 s
at 32 concurrent). An LRU result cache (`app/search/cache.py`, on by default via
`cache_size`) at a 94% hit-rate on Zipfian traffic lifts effective throughput
~15-20x and serves the median request in under 0.1 ms. The cold-miss tail stays
GIL-bound, so the next lever past the cache is multi-process workers, not a
bigger cache. Full percentile tables are in [BENCHMARKS.md](BENCHMARKS.md).

## Ranking evaluation + CI gate

Ranking changes are measured, not eyeballed. A hand-labeled judgment set
(`app/eval/qrels.py`) grades repos per query (0-3, keyed on repo full_name), and
**nDCG@10 / MRR / P@5** (`app/eval/metrics.py`, from scratch) score each ranker
variant. The eval runs against a **frozen snapshot of the full 157k-repo index**
with the labeled repos embedded, so the ranker has to surface them past 150k+ real
distractors:

```bash
python -m app.cli freeze-eval   # inject labels, build + freeze the eval index, write baseline
python -m app.cli evaluate      # score every ranker on the frozen index
python -m app.cli eval-gate     # fail if the shipped ranker regressed past the margin
```

| ranker           | nDCG@10 | 95% CI (bootstrap) |  MRR  |  P@5  |
|------------------|---------|--------------------|-------|-------|
| popularity_heavy |  0.513  | [0.385, 0.662]     | 0.625 | 0.320 |
| bm25f_v1         |  0.424  | [0.281, 0.595]     | 0.650 | 0.260 |
| bm25_v1          |  0.340  | [0.191, 0.522]     | 0.587 | 0.220 |
| bm25_only        |  0.183  | [0.057, 0.335]     | 0.326 | 0.100 |

At real-corpus scale the story inverts from a toy corpus: **pure BM25 collapses**
(0.183) because exact-lexical distractors bury the canonical repos, and
**popularity/field-weighted blending wins** by pulling the right repos into the
top-10. That is the whole argument for the blended ranker, now measured against
150k distractors instead of asserted.

**The gate** (`app/eval/gate.py`) fails the build if the shipped ranker's nDCG@10
drops more than `MARGIN` (0.05) below a committed baseline. Confidence intervals
are reported via bootstrap over the queries but are **not** gated on: at n=10 the
CI is wide (see the table) and would flap, so the gate uses the point estimate
with a stated margin and the coarseness is documented, not hidden. Full method and
per-query detail are in [BENCHMARKS.md](BENCHMARKS.md).

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
corpus; the tokenizer, engine (filters, blended ranking), ranking metrics, and
evaluation harness have unit tests too (31 in total).

## Roadmap

- Semantic search via embeddings + pgvector (hybrid BM25 + cosine)
- BM25F field weighting (name ≫ description ≫ README)
- Typo tolerance (trigram / edit distance)
- Redis result cache
