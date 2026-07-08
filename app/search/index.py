"""In-memory inverted index, persisted to a disk snapshot.

The index is a DERIVED artifact: it can always be rebuilt from Postgres. The API
loads the snapshot into memory at startup and serves queries from RAM.

Field-aware
-----------
A document is stored as a set of named FIELDS (e.g. name / description / topics /
readme) rather than one flat blob. For each term we keep its per-field term
frequencies, which is exactly what BM25F needs to weight a name match above a
README match. Plain BM25 still works: it just sums the per-field frequencies to
recover the whole-document term frequency, so the field split is invisible to it.

Callers that don't care about fields can still call
``add_document(doc_id, text, meta)`` — the text becomes a single default field
and BM25F degenerates to plain BM25.

Structures
----------
fields        : ordered list of field names (e.g. ["name", "description", ...])
postings      : term -> list[(doc_id, field_tfs)]  where field_tfs is a tuple of
                per-field term frequencies aligned to ``fields``
doc_field_len : doc_id -> tuple of per-field token counts (per-field length norm)
doc_len       : doc_id -> total token count (derived: sum of field lengths)
doc_meta      : doc_id -> compact metadata used for filtering (stars, language, ...)
N             : number of documents
avg_field_len : per-field mean length, aligned to ``fields``
avg_doc_len   : mean total document length (derived)

Display fields (description, url, ...) are NOT stored here; they're hydrated from
Postgres for the top-K results only. The index holds just what ranking + filtering
need, keeping it small enough to live in memory.
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from dataclasses import dataclass, field

from app.search.tokenizer import tokenize

# Field a bare ``add_document(doc_id, text, meta)`` call is filed under.
DEFAULT_FIELD = "body"


@dataclass
class DocMeta:
    stars: int = 0
    forks: int = 0
    language: str | None = None
    topics: tuple[str, ...] = ()
    pushed_at: float | None = None  # unix timestamp, for recency scoring/filtering


@dataclass
class InvertedIndex:
    postings: dict[str, list[tuple[int, tuple[int, ...]]]] = field(
        default_factory=lambda: defaultdict(list))
    doc_field_len: dict[int, tuple[int, ...]] = field(default_factory=dict)
    doc_meta: dict[int, DocMeta] = field(default_factory=dict)
    fields: list[str] = field(default_factory=list)
    N: int = 0
    avg_field_len: tuple[float, ...] = ()
    # Derived (computed in finalize / load) — kept for plain BM25 and stats.
    doc_len: dict[int, int] = field(default_factory=dict)
    avg_doc_len: float = 0.0

    # ---- build ----
    def add_document(self, doc_id: int, text: str | None = None,
                     meta: DocMeta | None = None, *,
                     fields: dict[str, str] | None = None) -> None:
        """Index a document.

        Pass either ``text`` (single default field) or ``fields`` (a mapping of
        field name -> text). The field set is fixed by the first document; every
        later document is projected onto that same ordered field list.
        """
        if meta is None:
            meta = DocMeta()
        if fields is None:
            fields = {DEFAULT_FIELD: text or ""}

        # The first document establishes the field order for the whole index.
        if not self.fields:
            self.fields = list(fields.keys())

        field_tokens = {f: tokenize(fields.get(f, "")) for f in self.fields}
        field_lens = tuple(len(field_tokens[f]) for f in self.fields)

        # Accumulate per-term, per-field frequencies for this document.
        per_term: dict[str, list[int]] = defaultdict(lambda: [0] * len(self.fields))
        for i, f in enumerate(self.fields):
            for tok in field_tokens[f]:
                per_term[tok][i] += 1

        for term, tfs in per_term.items():
            self.postings[term].append((doc_id, tuple(tfs)))

        # Register the doc even if it has no tokens, so filters can still return
        # it; it just won't match any term query.
        self.doc_field_len[doc_id] = field_lens
        self.doc_meta[doc_id] = meta

    def finalize(self) -> None:
        """Compute corpus-level stats after all docs are added."""
        self.N = len(self.doc_field_len)
        nf = len(self.fields)

        if self.N and nf:
            totals = [0] * nf
            for lens in self.doc_field_len.values():
                for i in range(nf):
                    totals[i] += lens[i]
            self.avg_field_len = tuple(t / self.N for t in totals)
        else:
            self.avg_field_len = tuple(0.0 for _ in self.fields)

        # Derived whole-document lengths for plain BM25 and stats.
        self.doc_len = {d: sum(lens) for d, lens in self.doc_field_len.items()}
        self.avg_doc_len = sum(self.avg_field_len)

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
        # doc_len / avg_doc_len are derived, so we don't persist them.
        payload = {
            "postings": dict(self.postings),
            "doc_field_len": self.doc_field_len,
            "doc_meta": self.doc_meta,
            "fields": self.fields,
            "N": self.N,
            "avg_field_len": self.avg_field_len,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: str) -> "InvertedIndex":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        idx = cls()
        idx.postings = defaultdict(list, payload["postings"])
        idx.doc_field_len = payload["doc_field_len"]
        idx.doc_meta = payload["doc_meta"]
        idx.fields = payload["fields"]
        idx.N = payload["N"]
        idx.avg_field_len = tuple(payload["avg_field_len"])
        # Recompute derived whole-document lengths.
        idx.doc_len = {d: sum(lens) for d, lens in idx.doc_field_len.items()}
        idx.avg_doc_len = sum(idx.avg_field_len)
        return idx
