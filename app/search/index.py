"""In-memory inverted index, persisted to a disk snapshot.

The index is a DERIVED artifact: it can always be rebuilt from Postgres. The API
loads the snapshot into memory at startup and serves queries from RAM.

Structures
----------
postings : term -> list[(doc_id, term_frequency)]
doc_len  : doc_id -> token count (for BM25 length normalization)
doc_meta : doc_id -> compact metadata used for filtering (stars, language, ...)
N        : number of documents
avg_doc_len : mean document length

Display fields (description, url, ...) are NOT stored here; they're hydrated from
Postgres for the top-K results only. The index holds just what ranking + filtering
need, keeping it small enough to live in memory.
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from dataclasses import dataclass, field

from app.search.tokenizer import tokenize


@dataclass
class DocMeta:
    stars: int = 0
    forks: int = 0
    language: str | None = None
    topics: tuple[str, ...] = ()
    pushed_at: float | None = None  # unix timestamp, for recency scoring/filtering


@dataclass
class InvertedIndex:
    postings: dict[str, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    doc_len: dict[int, int] = field(default_factory=dict)
    doc_meta: dict[int, DocMeta] = field(default_factory=dict)
    N: int = 0
    avg_doc_len: float = 0.0

    # ---- build ----
    def add_document(self, doc_id: int, text: str, meta: DocMeta) -> None:
        tokens = tokenize(text)
        if not tokens:
            # Still register the doc so it can be returned via filters, but it
            # won't match any term query.
            self.doc_len[doc_id] = 0
            self.doc_meta[doc_id] = meta
            return

        tf: dict[str, int] = defaultdict(int)
        for tok in tokens:
            tf[tok] += 1

        for term, freq in tf.items():
            self.postings[term].append((doc_id, freq))

        self.doc_len[doc_id] = len(tokens)
        self.doc_meta[doc_id] = meta

    def finalize(self) -> None:
        """Compute corpus-level stats after all docs are added."""
        self.N = len(self.doc_len)
        total = sum(self.doc_len.values())
        self.avg_doc_len = (total / self.N) if self.N else 0.0
        # Keep postings sorted by doc_id (enables future skip-list / merge tricks).
        for term in self.postings:
            self.postings[term].sort(key=lambda p: p[0])

    # ---- stats / introspection ----
    def doc_frequency(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def vocabulary_size(self) -> int:
        return len(self.postings)

    def total_postings(self) -> int:
        return sum(len(p) for p in self.postings.values())

    # ---- persistence ----
    def save(self, path: str) -> None:
        # defaultdict isn't needed once frozen; convert to plain dict for portability.
        payload = {
            "postings": dict(self.postings),
            "doc_len": self.doc_len,
            "doc_meta": self.doc_meta,
            "N": self.N,
            "avg_doc_len": self.avg_doc_len,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> "InvertedIndex":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        idx = cls()
        idx.postings = defaultdict(list, payload["postings"])
        idx.doc_len = payload["doc_len"]
        idx.doc_meta = payload["doc_meta"]
        idx.N = payload["N"]
        idx.avg_doc_len = payload["avg_doc_len"]
        return idx
