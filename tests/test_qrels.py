"""Sanity checks on the labeled judgment set, so it can't silently rot."""
from app.eval.qrels import QRELS
from app.ingest.seed_data import SEED_REPOS

SEED_IDS = {r["id"] for r in SEED_REPOS}


def test_judgments_reference_real_repos():
    for lq in QRELS:
        for doc_id in lq.judgments:
            assert doc_id in SEED_IDS, f"{lq.query!r} judges unknown repo {doc_id}"


def test_grades_in_range():
    for lq in QRELS:
        for doc_id, grade in lq.judgments.items():
            assert grade in (1, 2, 3), f"{lq.query!r} repo {doc_id} has bad grade {grade}"


def test_every_query_has_judgments():
    for lq in QRELS:
        assert lq.judgments, f"{lq.query!r} has no judgments"


def test_queries_are_unique():
    queries = [lq.query for lq in QRELS]
    assert len(queries) == len(set(queries))
