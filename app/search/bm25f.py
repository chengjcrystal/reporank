"""BM25F: field-weighted BM25, implemented from scratch over the inverted index.

Plain BM25 treats a repo as one flat bag of words, so a query term in the README
counts the same as one in the repo name. BM25F fixes that: it keeps each field
separate and boosts a term by which field it appears in.

For a document D and term q, the field-weighted (a.k.a. "pseudo") frequency is

    wtf(q, D) = sum over fields f of   boost_f * f(q, D, f) / B_f

    B_f = 1 - b + b * len_f(D) / avglen_f

where f(q, D, f) is q's frequency in field f of D, boost_f is the field's weight
(name >> description >= topics >> readme), and B_f length-normalizes *within the
field* so a hit in a short name isn't drowned out by a long README. The pseudo
frequency then goes through the usual BM25 saturation:

    score(q, D) = IDF(q) * wtf * (k1 + 1) / (k1 + wtf)

IDF is identical to plain BM25 (document frequency = docs containing q in ANY
field), so rare terms still dominate.

Note the length normalization lives *inside* each field here, which is why the
outer saturation has no separate ``b`` term — that job is already done per field.

Degenerate case worth knowing: with a single field and boost 1.0 this reduces
*exactly* to plain BM25 (see tests), so BM25F is a strict generalization, not a
different model.
"""
from __future__ import annotations

import math
from collections import defaultdict

from app.search.index import InvertedIndex
from app.search.tokenizer import tokenize

# Field boosts. Unlisted fields default to 1.0; DEFAULT_FIELD ("body") keeps the
# single-field case equivalent to plain BM25.
DEFAULT_FIELD_BOOSTS: dict[str, float] = {
    "name": 4.0,
    "description": 2.0,
    "topics": 2.0,
    "readme": 1.0,
    "body": 1.0,
}


class BM25F:
    def __init__(self, index: InvertedIndex, k1: float = 1.5, b: float = 0.75,
                 field_boosts: dict[str, float] | None = None):
        self.index = index
        self.k1 = k1
        self.b = b
        boosts = field_boosts or DEFAULT_FIELD_BOOSTS
        # Align boosts to the index's field order once, up front.
        self.boosts = tuple(boosts.get(f, 1.0) for f in index.fields)

    def idf(self, term: str) -> float:
        df = self.index.doc_frequency(term)
        if df == 0:
            return 0.0
        n = self.index.N
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score_terms(self, terms: list[str]) -> dict[int, float]:
        """Return {doc_id: bm25f_score} for every doc matching any query term."""
        idx = self.index
        k1, b = self.k1, self.b
        avg = idx.avg_field_len
        boosts = self.boosts
        scores: dict[int, float] = defaultdict(float)

        for term in terms:
            postings = idx.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            if idf == 0.0:
                continue
            for doc_id, field_tfs in postings:
                lens = idx.doc_field_len[doc_id]
                wtf = 0.0
                for i, tf in enumerate(field_tfs):
                    if tf == 0:
                        continue
                    avg_i = avg[i] or 1.0
                    b_norm = 1 - b + b * lens[i] / avg_i
                    wtf += boosts[i] * tf / b_norm
                if wtf == 0.0:
                    continue
                scores[doc_id] += idf * wtf * (k1 + 1) / (k1 + wtf)

        return scores

    def search(self, query: str) -> dict[int, float]:
        return self.score_terms(tokenize(query))
