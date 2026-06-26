"""BM25 correctness on a tiny, fully-controlled corpus.

We validate against an independent reference implementation computed directly
from the raw documents, so this also exercises index building (df, doc lengths,
avgdl) end to end.
"""
import math

import pytest

from app.search.bm25 import BM25
from app.search.index import DocMeta, InvertedIndex

# Terms chosen to avoid the stopword list.
CORPUS = {
    1: "cat cat dog",
    2: "dog bird",
    3: "cat bird fish",
}


def build():
    idx = InvertedIndex()
    for doc_id, text in CORPUS.items():
        idx.add_document(doc_id, text, DocMeta())
    idx.finalize()
    return idx


def reference_score(query_terms, k1=1.5, b=0.75):
    docs = {d: t.split() for d, t in CORPUS.items()}
    N = len(docs)
    avgdl = sum(len(t) for t in docs.values()) / N
    scores = {}
    for d, toks in docs.items():
        s = 0.0
        for q in query_terms:
            df = sum(1 for t in docs.values() if q in t)
            if df == 0:
                continue
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            tf = toks.count(q)
            if tf == 0:
                continue
            denom = tf + k1 * (1 - b + b * len(toks) / avgdl)
            s += idf * (tf * (k1 + 1)) / denom
        if s:
            scores[d] = s
    return scores


def test_corpus_stats():
    idx = build()
    assert idx.N == 3
    assert idx.avg_doc_len == pytest.approx(8 / 3)
    assert idx.doc_frequency("cat") == 2
    assert idx.doc_frequency("fish") == 1


def test_idf_matches_formula():
    idx = build()
    bm25 = BM25(idx)
    assert bm25.idf("cat") == pytest.approx(math.log(1 + (3 - 2 + 0.5) / (2 + 0.5)))


def test_scores_match_reference():
    idx = build()
    bm25 = BM25(idx)
    got = bm25.score_terms(["cat"])
    expected = reference_score(["cat"])
    assert set(got) == set(expected)
    for d in expected:
        assert got[d] == pytest.approx(expected[d])


def test_higher_tf_ranks_higher():
    idx = build()
    bm25 = BM25(idx)
    scores = bm25.score_terms(["cat"])
    # doc1 has "cat" twice, doc3 once -> doc1 must outrank doc3.
    assert scores[1] > scores[3]
    # doc2 has no "cat" -> excluded.
    assert 2 not in scores


def test_multi_term_query_accumulates():
    idx = build()
    bm25 = BM25(idx)
    assert bm25.score_terms(["cat", "bird"]) == pytest.approx(reference_score(["cat", "bird"]))
