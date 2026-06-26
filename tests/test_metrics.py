"""Metric tests: validated against hand-computed values."""
import math

from app.eval.metrics import (
    dcg,
    mean,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
)


def test_dcg_matches_hand_computation():
    # gains [3, 2, 1] -> 3/log2(2) + 2/log2(3) + 1/log2(4)
    expected = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert dcg([3, 2, 1]) == expected


def test_ndcg_perfect_ranking_is_one():
    qrels = {1: 3.0, 2: 2.0, 3: 1.0}
    assert ndcg_at_k([1, 2, 3], qrels, k=3) == 1.0


def test_ndcg_penalizes_suboptimal_order():
    qrels = {1: 3.0, 2: 2.0, 3: 1.0}
    # best doc demoted to last -> below perfect
    score = ndcg_at_k([3, 2, 1], qrels, k=3)
    assert 0.0 < score < 1.0


def test_ndcg_no_relevant_docs_is_zero():
    assert ndcg_at_k([1, 2, 3], {}, k=3) == 0.0


def test_ndcg_known_value():
    # qrels grades {a:3, b:2, c:1}; ranking puts c first.
    qrels = {1: 3.0, 2: 2.0, 3: 1.0}
    actual = 1 / math.log2(2) + 2 / math.log2(3) + 3 / math.log2(4)
    ideal = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k([3, 2, 1], qrels, k=3) == actual / ideal


def test_reciprocal_rank_first_relevant():
    qrels = {5: 2.0}
    assert reciprocal_rank([1, 2, 5, 9], qrels) == 1 / 3


def test_reciprocal_rank_none_relevant():
    assert reciprocal_rank([1, 2, 3], {9: 1.0}) == 0.0


def test_precision_at_k():
    qrels = {1: 1.0, 3: 2.0}
    # top-4 ranking, 2 relevant -> 0.5
    assert precision_at_k([1, 2, 3, 4], qrels, k=4) == 0.5


def test_mean_empty_is_zero():
    assert mean([]) == 0.0
