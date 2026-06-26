"""Evaluator tests on a small synthetic index, independent of the seed data."""
from app.eval import evaluate
from app.eval.qrels import LabeledQuery
from app.search.engine import SearchEngine
from app.search.index import DocMeta, InvertedIndex

NOW = evaluate.EVAL_NOW
DAY = 86400.0


def _engine():
    idx = InvertedIndex()
    idx.add_document(1, "redis in memory database cache key value", DocMeta(
        stars=60000, language="C", topics=("database", "cache"), pushed_at=NOW - 10 * DAY))
    idx.add_document(2, "fastapi python web framework backend api", DocMeta(
        stars=70000, language="Python", topics=("fastapi", "api"), pushed_at=NOW - 5 * DAY))
    idx.add_document(3, "react javascript frontend ui library", DocMeta(
        stars=200000, language="JavaScript", topics=("react", "ui"), pushed_at=NOW - 5 * DAY))
    idx.finalize()
    return SearchEngine(idx)


def test_perfect_ranking_scores_one(monkeypatch):
    # A single query whose only relevant doc is the obvious top hit.
    monkeypatch.setattr(evaluate, "QRELS", [
        LabeledQuery("redis cache", {1: 3}),
    ])
    report = evaluate.evaluate_ranker(_engine(), "bm25_only")
    assert report.ndcg == 1.0
    assert report.mrr == 1.0


def test_metrics_are_bounded(monkeypatch):
    monkeypatch.setattr(evaluate, "QRELS", [
        LabeledQuery("redis cache", {1: 3}),
        LabeledQuery("python web framework", {2: 3}),
        LabeledQuery("react frontend", {3: 3}),
    ])
    for report in evaluate.evaluate_all(_engine()):
        assert 0.0 <= report.ndcg <= 1.0
        assert 0.0 <= report.mrr <= 1.0
        assert 0.0 <= report.precision <= 1.0


def test_report_covers_all_rankers(monkeypatch):
    monkeypatch.setattr(evaluate, "QRELS", [LabeledQuery("redis cache", {1: 3})])
    reports = evaluate.evaluate_all(_engine())
    assert {r.ranker for r in reports} == {"bm25_only", "bm25_v1", "popularity_heavy"}
