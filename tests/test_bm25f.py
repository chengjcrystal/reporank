"""BM25F correctness: reduces to BM25 on one field, and weights fields as configured."""
import pytest

from app.search.bm25 import BM25
from app.search.bm25f import BM25F
from app.search.index import DocMeta, InvertedIndex


def _single_field_index():
    """Same corpus as the BM25 tests, but exercised through the field machinery."""
    idx = InvertedIndex()
    for doc_id, text in {1: "cat cat dog", 2: "dog bird", 3: "cat bird fish"}.items():
        idx.add_document(doc_id, text, DocMeta())  # -> single "body" field
    idx.finalize()
    return idx


def _multi_field_index():
    idx = InvertedIndex()
    # doc1: query term "redis" is the NAME. doc2: "redis" only buried in README.
    idx.add_document(1, meta=DocMeta(), fields={
        "name": "redis", "description": "in memory store", "topics": "cache", "readme": "docs"})
    idx.add_document(2, meta=DocMeta(), fields={
        "name": "tutorial", "description": "learn caching", "topics": "guide",
        "readme": "we clone redis from scratch as an exercise"})
    idx.finalize()
    return idx


def test_reduces_to_bm25_on_single_field():
    idx = _single_field_index()
    bm25 = BM25(idx)
    # boost 1.0 on the lone "body" field -> BM25F must equal BM25 exactly.
    bm25f = BM25F(idx, field_boosts={"body": 1.0})
    for query in (["cat"], ["cat", "bird"], ["dog"]):
        got = bm25f.score_terms(query)
        expected = bm25.score_terms(query)
        assert set(got) == set(expected)
        for d in expected:
            assert got[d] == pytest.approx(expected[d])


def test_name_match_outranks_readme_match():
    idx = _multi_field_index()
    scores = BM25F(idx).score_terms(["redis"])
    # Both docs contain "redis", but doc1 has it in the (heavily boosted) name.
    assert scores[1] > scores[2]


def test_boosts_change_ranking():
    idx = _multi_field_index()
    # With README boosted far above name, the README doc should win instead.
    flipped = BM25F(idx, field_boosts={
        "name": 1.0, "description": 1.0, "topics": 1.0, "readme": 50.0})
    scores = flipped.score_terms(["redis"])
    assert scores[2] > scores[1]
