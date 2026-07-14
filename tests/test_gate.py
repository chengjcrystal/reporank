"""Tests for the bootstrap CI and the ranking-regression gate."""
from pathlib import Path

import pytest

from app.config import settings
from app.eval.gate import bootstrap_ci


def test_bootstrap_ci_point_is_the_mean_and_is_bracketed():
    vals = [0.2, 0.4, 0.6, 0.8, 1.0]
    point, lo, hi = bootstrap_ci(vals, seed=0)
    assert abs(point - 0.6) < 1e-9
    assert lo <= point <= hi


def test_bootstrap_ci_is_deterministic():
    vals = [0.1, 0.3, 0.9, 0.5, 0.7, 0.2]
    assert bootstrap_ci(vals, seed=0) == bootstrap_ci(vals, seed=0)


def test_bootstrap_ci_zero_variance_collapses():
    point, lo, hi = bootstrap_ci([0.5] * 8, seed=0)
    assert point == 0.5 and lo == 0.5 and hi == 0.5


@pytest.mark.skipif(
    not Path(settings.eval_index_path).exists(),
    reason="frozen eval index not materialized; run `python -m app.cli freeze-eval`")
def test_gated_ranker_meets_floor():
    """The actual CI gate: the shipped ranker must not regress past the margin.

    Skips (does not fail) where the frozen index has not been built, so a fresh
    clone or a cloud runner without the snapshot stays green; it runs wherever the
    snapshot is materialized (local / dev CI)."""
    from app.eval.gate import run_gate

    res = run_gate()
    assert res["passed"], (
        f"ranking regression: {res['ranker']} nDCG@10={res['ndcg']} "
        f"fell below floor {res['floor']} (baseline {res['baseline']})")
