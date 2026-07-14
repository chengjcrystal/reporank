"""Tests for the LRU result cache and the engine's use of it."""
from __future__ import annotations

import pytest

from app.search.cache import LRUCache
from app.search.engine import SearchEngine
from app.search.index import DocMeta, InvertedIndex


def _tiny_index() -> InvertedIndex:
    idx = InvertedIndex()
    idx.add_document(1, meta=DocMeta(stars=100), fields={
        "name": "redis", "description": "in memory key value store",
        "topics": "database cache", "readme": ""})
    idx.add_document(2, meta=DocMeta(stars=50), fields={
        "name": "kafka", "description": "distributed event streaming",
        "topics": "streaming", "readme": ""})
    idx.finalize()
    return idx


def test_lru_evicts_least_recently_used():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1      # touch 'a' so 'b' is now the LRU
    c.put("c", 3)               # inserting a third evicts 'b'
    assert c.get("b") is None
    assert c.get("a") == 1
    assert c.get("c") == 3


def test_hit_rate_tracking():
    c = LRUCache(8)
    c.put("k", "v")
    c.get("k")        # hit
    c.get("missing")  # miss
    assert c.hits == 1
    assert c.misses == 1
    assert c.hit_rate == 0.5


def test_zero_capacity_rejected():
    with pytest.raises(ValueError):
        LRUCache(0)


def test_engine_serves_repeat_query_from_cache():
    eng = SearchEngine(_tiny_index(), cache_size=16)
    first = eng.search("distributed streaming")
    assert eng.cache.misses == 1 and eng.cache.hits == 0
    second = eng.search("distributed streaming")
    assert eng.cache.hits == 1
    assert first is second   # exact cached object handed back


def test_explicit_clock_bypasses_cache():
    eng = SearchEngine(_tiny_index(), cache_size=16)
    eng.search("redis", now=1_000_000.0)
    eng.search("redis", now=1_000_000.0)
    # An explicit `now` must not touch the cache (keeps eval reproducible).
    assert eng.cache.hits == 0 and eng.cache.misses == 0


def test_cache_disabled_by_default():
    eng = SearchEngine(_tiny_index())
    assert eng.cache is None
    eng.search("redis")  # must not raise with caching off
