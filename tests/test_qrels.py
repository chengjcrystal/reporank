"""Sanity checks on the labeled judgment set, so it can't silently rot."""
from app.eval.qrels import QRELS, SYNTHETIC, labeled_full_names


def test_grades_in_range():
    for lq in QRELS:
        for fn, grade in lq.judgments.items():
            assert grade in (1, 2, 3), f"{lq.query!r} repo {fn} has bad grade {grade}"


def test_every_query_has_judgments():
    for lq in QRELS:
        assert lq.judgments, f"{lq.query!r} has no judgments"


def test_queries_are_unique():
    queries = [lq.query for lq in QRELS]
    assert len(queries) == len(set(queries))


def test_full_names_look_like_owner_repo():
    for fn in labeled_full_names():
        owner, sep, name = fn.partition("/")
        assert sep and owner and name, f"{fn!r} is not a valid owner/name"


def test_synthetic_labels_are_actually_labeled():
    # Every name marked synthetic must appear in the judgments, or it is dead.
    assert SYNTHETIC <= labeled_full_names()
