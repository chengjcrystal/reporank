"""A small thread-safe LRU cache for search results.

Search scoring is CPU-bound: a broad multi-term query scores tens of thousands of
candidate documents term-at-a-time. Real query traffic is heavily skewed (a few
queries repeat a lot), so caching the ranked result of a (query, filters, ranker,
page) key turns those repeats into a dict lookup and takes them off the hot path.

The cache tracks hits/misses so the hit-rate can be reported, and it is bounded by
an LRU eviction policy so memory stays flat under an unbounded query stream.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Hashable


class LRUCache:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._store: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)  # mark most-recently-used
                self.hits += 1
                return self._store[key]
            self.misses += 1
            return None

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            if len(self._store) > self.capacity:
                self._store.popitem(last=False)  # evict least-recently-used

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def stats(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "size": len(self._store),
                "capacity": self.capacity,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hit_rate, 4),
            }
