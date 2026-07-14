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
