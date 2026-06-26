"""Ranking quality metrics, implemented from scratch.

These operate on a *ranked list of doc_ids* plus a *relevance map* (qrels):
doc_id -> graded relevance (0 = irrelevant, higher = more relevant). Graded
relevance is what lets nDCG reward putting the *best* result first, not just a
relevant one — the distinction that matters when comparing ranker variants.

All functions are pure and take the ranking + qrels explicitly so they're
trivially unit-testable against hand-computed values.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain over an ordered list of gains.

    Uses the standard log2(rank+1) discount: gain at rank i (1-based) is
    divided by log2(i + 1), so rank 1 is undiscounted, rank 2 by log2(3), etc.
    """
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranking: Sequence[int], qrels: dict[int, float], k: int) -> float:
    """Normalized DCG over the top-k of `ranking`.

    Normalized against the ideal ranking (qrels sorted by relevance desc), so
    the result is in [0, 1] and comparable across queries with different numbers
    of relevant docs. Returns 0.0 when the query has no relevant docs.
    """
    gains = [qrels.get(doc_id, 0.0) for doc_id in ranking[:k]]
    actual = dcg(gains)

    ideal_gains = sorted(qrels.values(), reverse=True)[:k]
    ideal = dcg(ideal_gains)
    if ideal == 0.0:
        return 0.0
    return actual / ideal


def reciprocal_rank(ranking: Sequence[int], qrels: dict[int, float]) -> float:
    """1 / rank of the first relevant (grade > 0) doc; 0 if none appear."""
    for i, doc_id in enumerate(ranking):
        if qrels.get(doc_id, 0.0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def precision_at_k(ranking: Sequence[int], qrels: dict[int, float], k: int) -> float:
    """Fraction of the top-k that are relevant (grade > 0)."""
    if k <= 0:
        return 0.0
    relevant = sum(1 for doc_id in ranking[:k] if qrels.get(doc_id, 0.0) > 0)
    return relevant / k


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
