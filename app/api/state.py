"""Process-wide search engine holder.

The index lives in memory for the life of the process. We load the snapshot once
at startup and rebuild the SearchEngine around it. `reload()` lets us swap in a
freshly built index without restarting (e.g. after a crawl).
"""
from __future__ import annotations

import os

from app.config import settings
from app.search.engine import SearchEngine
from app.search.index import InvertedIndex


class EngineState:
    def __init__(self) -> None:
        self.engine: SearchEngine | None = None

    def reload(self) -> bool:
        if not os.path.exists(settings.index_path):
            self.engine = None
            return False
        index = InvertedIndex.load(settings.index_path)
        self.engine = SearchEngine(index)
        return True

    def require(self) -> SearchEngine:
        if self.engine is None:
            raise RuntimeError(
                "Search index not loaded. Run: python -m app.cli seed && "
                "python -m app.cli build-index"
            )
        return self.engine


state = EngineState()
