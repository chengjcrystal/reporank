"""BM25 ranking, implemented from scratch over the inverted index.

score(D, Q) = sum over q in Q of:

    IDF(q) * ( f(q,D) * (k1 + 1) ) / ( f(q,D) + k1 * (1 - b + b * |D| / avgdl) )

    IDF(q) = ln( 1 + (N - df(q) + 0.5) / (df(q) + 0.5) )

where
    f(q,D) = frequency of term q in document D
    |D|    = length of D in tokens
    avgdl  = average document length
    N      = number of documents
    df(q)  = number of documents containing q
    k1     = term-frequency saturation (default 1.5)
    b      = length normalization (default 0.75)

We score term-at-a-time: walk each query term's postings list and accumulate
partial scores into a per-document accumulator. Only documents that contain at
least one query term are ever touched.
"""
from __future__ import annotations

import math
from collections import defaultdict

from app.search.index import InvertedIndex
from app.search.tokenizer import tokenize


class BM25:
    def __init__(self, index: InvertedIndex, k1: float = 1.5, b: float = 0.75):
        self.index = index
        self.k1 = k1
        self.b = b

    def idf(self, term: str) -> float:
        df = self.index.doc_frequency(term)
        if df == 0:
            return 0.0
        n = self.index.N
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score_terms(self, terms: list[str]) -> dict[int, float]:
        """Return {doc_id: bm25_score} for every doc matching any query term."""
        idx = self.index
        k1, b, avgdl = self.k1, self.b, idx.avg_doc_len or 1.0
        scores: dict[int, float] = defaultdict(float)

        for term in terms:
            postings = idx.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            if idf == 0.0:
                continue
            for doc_id, field_tfs in postings:
                # Plain BM25 is field-agnostic: recover the whole-document term
                # frequency by summing the per-field counts.
                tf = sum(field_tfs)
                dl = idx.doc_len.get(doc_id, 0)
                denom = tf + k1 * (1 - b + b * dl / avgdl)
                scores[doc_id] += idf * (tf * (k1 + 1)) / denom

        return scores

    def search(self, query: str) -> dict[int, float]:
        return self.score_terms(tokenize(query))
