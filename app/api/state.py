"""Process-wide search engine holder.

The index lives in memory for the life of the process. We load the snapshot once
at startup and rebuild the SearchEngine around it. `reload()` lets us swap in a
freshly built index without restarting (e.g. after a crawl).

The swap is done off to the side: the new engine is built fully before it
replaces the old one, so in-flight requests keep serving the old index until the
new one is ready, and the reference swap itself happens under a lock so a reload
can never hand a request a half-built engine.
"""
from __future__ import annotations

import os
import threading

from app.config import settings
from app.search.engine import SearchEngine
from app.search.index import InvertedIndex


class EngineState:
    def __init__(self) -> None:
        self.engine: SearchEngine | None = None
        self._lock = threading.Lock()

    def reload(self) -> bool:
        if not os.path.exists(settings.index_path):
            with self._lock:
                self.engine = None
            return False
        # Build the new engine before swapping, so live requests keep serving the
        # current index until the replacement is fully ready.
        index = InvertedIndex.load(settings.index_path)
        new_engine = SearchEngine(index, cache_size=settings.cache_size)
        with self._lock:
            self.engine = new_engine
        return True

    def require(self) -> SearchEngine:
        engine = self.engine  # atomic reference read
        if engine is None:
            raise RuntimeError(
                "Search index not loaded. Run: python -m app.cli seed && "
                "python -m app.cli build-index"
            )
        return engine


state = EngineState()
