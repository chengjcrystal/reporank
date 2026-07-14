# RepoRank: GitHub Repository Search Engine

**In plain terms:** GitHub's search matches keywords, so genuinely strong repos get
buried under name-collisions and forks. RepoRank re-ranks repository search by
combining how well a repo's text matches your query with how strong the project is
(stars, recency), and it measures whether that ranking is actually better on a
hand-labeled test set instead of assuming it.

Under the hood: a **custom inverted index** and **BM25 / BM25F ranking built from
scratch** (no Elasticsearch / Algolia), a quality-aware blended ranker (text
relevance + popularity + recency), and a ranking-regression gate that scores
nDCG / MRR / P@5 against a frozen **157,083-repo** index in CI.

> **157k** repos crawled · index loads in **0.6 s** · **~100 QPS** single-process,
> **15-20x** with the cache · **49 tests** + a ranking gate running in CI

```
distributed systems projects   ·   FastAPI PostgreSQL applications
computer vision with deployment ·   projects similar to Redis
```

![RepoRank search UI](docs/screenshot.png)

Searching the real 157k-repo index: field-weighted ranking by default, live
language / stars / topic filters, and a per-query latency badge. Searches are
deep-linkable (`/?q=distributed+systems+projects`).

## Architecture

```
GitHub API ──▶ Crawler ──▶ SQLite by default ──▶ Indexer ──▶ snapshot.pkl
 (rate-limit,   (resumable   (Postgres optional)  (tokenize,    (in-memory
  star-slice)    crawl_state)  repos / topics /    inverted      inverted
                              search_logs)         index)        index)
                                                                    │
                     vanilla-JS SPA  ◀──  FastAPI  ◀── BM25F + filters + blended re-rank
```

The **ingestion** path (offline batch) is cleanly separated from the **serving**
path (online, in-memory, low-latency). The search index is a *derived artifact*:
it can always be rebuilt from the database.

## Quickstart (zero setup, uses SQLite + seed data)

```bash
cd reporank
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m app.cli seed          # load the 30-repo offline demo set
python -m app.cli build-index   # build + persist the inverted index
uvicorn app.main:app --reload   # open http://localhost:8000
```

The seed set is a 30-repo demo so the app runs with no token. The real corpus
(157k repos) comes from the crawler below.

Then open **http://localhost:8000** for the search UI (a dark GitHub-style SPA with
autocomplete, language / stars / topic filters, per-result score and latency
badges, and an analytics panel) and try `distributed systems projects` or
`FastAPI PostgreSQL`. Auto-generated API docs live at **/docs**.

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

- **Tokenizer** (`app/search/tokenizer.py`): lowercase, tech-aware (keeps `c++`,
  `node.js`), curated stopwords, identical for indexing and querying.
- **Inverted index** (`app/search/index.py`): `term → [(doc_id, tf)]`, doc
  lengths, corpus stats; persisted as a snapshot, loaded into RAM.
- **BM25** (`app/search/bm25.py`): term-at-a-time scoring, from scratch.
- **BM25F** (`app/search/bm25f.py`): field-weighted BM25 from scratch (name >
  description/topics > readme), reducing to plain BM25 on a single field.
- **Blended ranker** (`app/search/engine.py`):
  `final = w_text·bm25 + w_pop·log(stars) + w_fresh·recency`, selectable via the
  `ranker` query param for A/B experiments. Variants: `bm25f_v1` (shipped default,
  field-weighted), `bm25_v1` (flat), `bm25_only`, `popularity_heavy`.
- **Result cache** (`app/search/cache.py`): in-process LRU over
  (query, filters, ranker, page), on by default via `cache_size`.

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
| **bm25f_v1** (shipped) | 0.424 | [0.281, 0.595] | 0.650 | 0.260 |
| bm25_v1          |  0.340  | [0.191, 0.522]     | 0.587 | 0.220 |
| bm25_only        |  0.183  | [0.057, 0.335]     | 0.326 | 0.100 |

At real-corpus scale the story inverts from a toy corpus. Pure BM25 collapses to
0.183 because exact-lexical distractors bury the canonical repos, and blending in
quality signal is what pulls the right repos into the top-10. That is the whole
argument for the blended ranker, now backed by measurement against 150k
distractors rather than intuition.

**Why `bm25f_v1` ships instead of the top-scoring ranker.** popularity_heavy
has the higher point estimate (0.513 vs 0.424), but at n=10 the CIs overlap
heavily, so the two are a statistical tie, not a ranking. The tie breaks on
robustness: popularity_heavy (0.8 star weight) wins only on head queries where the
relevant repo is already the most-starred, and it fails on specific / tail queries
by sorting popular-but-off-topic repos to the top (e.g. `raft consensus algorithm`:
0.333 vs bm25f_v1's 0.527, because `tikv/raft-rs` is on-topic but not a mega-star).
bm25f_v1 is content-driven and is the field-weighting the project exists to
demonstrate, so it ships; popularity_heavy stays as a documented comparison.

**The gate** (`app/eval/gate.py`) fails the build if the shipped ranker's nDCG@10
drops more than `MARGIN` (0.05) below a committed baseline, scored in CI against
the frozen index (downloaded from a release asset). Full method and per-query
detail are in [BENCHMARKS.md](BENCHMARKS.md).

### Known limitations of the eval

This judgment set is small, and the numbers come with two honest caveats:

- **n=10 queries: the top two rankers are statistically indistinguishable.** The
  bootstrap 95% CIs overlap heavily (popularity_heavy [0.385, 0.662] vs bm25f_v1
  [0.281, 0.595]), so their 0.09 point-estimate gap is not a real ranking. This is
  exactly why the gate is on the point estimate with a fixed margin rather than on
  a CI bound, which at this n would flap on noise.
- **Shallow pools bias the absolute numbers down.** Only ~27 repos across the 10
  queries are judged, so most of each ranker's top-10 is unjudged and scored as
  non-relevant. That depresses every nDCG@10 and can bias the between-ranker
  comparison (a ranker surfacing genuinely relevant but unjudged repos is punished
  for it). The scores are useful for regression detection and relative comparison,
  not as absolute relevance.

The **highest-leverage next eval step is pooling**: take the union of each ranker's
top-k per query, judge that pool, and re-score. That removes the unjudged-as-
non-relevant bias far more cheaply than blindly writing more queries, so it comes
before any query-set expansion.

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

BM25 and BM25F are validated against independent / hand-computed reference values;
the tokenizer, engine (filters, blended ranking, cache), ranking metrics, crawler
retry logic, and the eval gate have unit tests too (49 in total). CI runs the full
suite on every push, including the ranking-regression gate against the frozen
index.

## Roadmap

- **Pooling for the eval** (union each ranker's top-k, judge, re-score): the
  highest-leverage next step, removes the shallow-pool bias above before expanding
  the query set.
- Multi-process serving workers to lift the single-process GIL ceiling on
  throughput (see the latency section).
- Semantic search via embeddings + pgvector (hybrid BM25 + cosine).
- Typo tolerance (trigram / edit distance).
- Shared / cross-process result cache (the current cache is in-process LRU).
