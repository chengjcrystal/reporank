"""Engine-level tests: filtering and blended ranking behavior."""
from app.search.engine import Filters, SearchEngine
from app.search.index import DocMeta, InvertedIndex

NOW = 1_750_000_000.0  # fixed clock so recency is deterministic
DAY = 86400.0


def build():
    idx = InvertedIndex()
    idx.add_document(1, "redis in memory database cache", DocMeta(
        stars=60000, language="C", topics=("database", "cache"), pushed_at=NOW - 10 * DAY))
    idx.add_document(2, "redis clone tutorial beginner", DocMeta(
        stars=500, language="Python", topics=("tutorial", "redis"), pushed_at=NOW - 5 * DAY))
    idx.add_document(3, "fastapi postgres backend", DocMeta(
        stars=2000, language="Python", topics=("fastapi", "postgresql"), pushed_at=NOW - 400 * DAY))
    idx.finalize()
    return SearchEngine(idx)


def test_filter_by_language():
    eng = build()
    hits, total = eng.search("redis", filters=Filters(language="Python"), now=NOW)
    ids = {h.doc_id for h in hits}
    assert ids == {2}
    assert total == 1


def test_filter_by_min_stars():
    eng = build()
    hits, _ = eng.search("redis", filters=Filters(min_stars=1000), now=NOW)
    assert {h.doc_id for h in hits} == {1}


def test_filter_by_topic_and_semantics():
    eng = build()
    hits, _ = eng.search("", filters=Filters(topics=("database", "cache")), now=NOW)
    assert {h.doc_id for h in hits} == {1}


def test_popularity_blending_changes_order():
    eng = build()
    # Both docs match "redis"; doc1 has far more stars. Popularity-weighted
    # ranker should put the popular one first.
    hits, _ = eng.search("redis", ranker="popularity_heavy", now=NOW)
    assert hits[0].doc_id == 1


def test_empty_query_browses_by_quality():
    eng = build()
    hits, total = eng.search("", now=NOW)
    assert total == 3            # no terms -> all docs are candidates
    assert hits[0].doc_id == 1   # highest stars + recent
