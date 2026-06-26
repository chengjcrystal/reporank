"""Offline evaluation: score each ranker variant on the labeled query set.

This is the relevance-experiment harness. For every labeled query it runs the
search engine under each ranker variant, then scores the returned ranking
against the hand-labeled judgments with nDCG@k / MRR / P@k. Averaging over the
query set turns "I built ranking variants" into "variant X beats Y by N nDCG",
which is the comparison that actually demonstrates the ranking work.

The engine is fed a fixed `now` so recency scoring is deterministic and runs
are reproducible across days.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.eval import metrics
from app.eval.qrels import QRELS, LabeledQuery
from app.search.engine import RANKERS, SearchEngine

# Fixed clock for reproducible recency scoring (matches the seed data era).
EVAL_NOW = 1_751_000_000.0  # ~2025-06-27
NDCG_K = 10
PRECISION_K = 5
TOP_N = 20  # ranking depth pulled from the engine before scoring


@dataclass
class RankerReport:
    ranker: str
    ndcg: float
    mrr: float
    precision: float
    per_query_ndcg: dict[str, float]


def _ranking_for(engine: SearchEngine, lq: LabeledQuery, ranker: str) -> list[int]:
    hits, _ = engine.search(lq.query, ranker=ranker, per_page=TOP_N, now=EVAL_NOW)
    return [h.doc_id for h in hits]


def evaluate_ranker(engine: SearchEngine, ranker: str) -> RankerReport:
    ndcgs: list[float] = []
    rrs: list[float] = []
    precisions: list[float] = []
    per_query: dict[str, float] = {}

    for lq in QRELS:
        qrels = {doc_id: float(g) for doc_id, g in lq.judgments.items()}
        ranking = _ranking_for(engine, lq, ranker)
        n = metrics.ndcg_at_k(ranking, qrels, NDCG_K)
        ndcgs.append(n)
        rrs.append(metrics.reciprocal_rank(ranking, qrels))
        precisions.append(metrics.precision_at_k(ranking, qrels, PRECISION_K))
        per_query[lq.query] = n

    return RankerReport(
        ranker=ranker,
        ndcg=metrics.mean(ndcgs),
        mrr=metrics.mean(rrs),
        precision=metrics.mean(precisions),
        per_query_ndcg=per_query,
    )


def evaluate_all(engine: SearchEngine) -> list[RankerReport]:
    return [evaluate_ranker(engine, r) for r in RANKERS]


def format_report(reports: list[RankerReport]) -> str:
    lines = [
        f"Evaluation over {len(QRELS)} labeled queries "
        f"(nDCG@{NDCG_K}, MRR, P@{PRECISION_K})",
        "",
        f"{'ranker':<18}{'nDCG':>8}{'MRR':>8}{'P@'+str(PRECISION_K):>8}",
        "-" * 42,
    ]
    for r in sorted(reports, key=lambda r: r.ndcg, reverse=True):
        lines.append(f"{r.ranker:<18}{r.ndcg:>8.3f}{r.mrr:>8.3f}{r.precision:>8.3f}")
    return "\n".join(lines)
