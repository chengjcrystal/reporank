"""Offline evaluation: score each ranker variant on the labeled query set.

This is the relevance-experiment harness. For every labeled query it runs the
search engine under each ranker variant, then scores the returned ranking against
the judgments with nDCG@k / MRR / P@k. Averaging over the query set turns "I built
ranking variants" into "variant X beats Y by N nDCG", the comparison that actually
demonstrates the ranking work.

The evaluator takes judgments as a resolved `query -> {doc_id: grade}` map, so it
is decoupled from how labels are stored (the real run resolves full_name labels to
doc_ids against the frozen index; tests pass a small map directly). The engine is
fed a fixed `now` so recency scoring is deterministic across runs.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.eval import metrics
from app.search.engine import RANKERS, SearchEngine

# Fixed clock for reproducible recency scoring.
EVAL_NOW = 1_751_000_000.0  # ~2025-06-27
NDCG_K = 10
PRECISION_K = 5
TOP_N = 50  # ranking depth pulled from the engine before scoring

QrelsByQuery = dict[str, dict[int, float]]  # query -> {doc_id: grade}


@dataclass
class RankerReport:
    ranker: str
    ndcg: float
    mrr: float
    precision: float
    per_query_ndcg: dict[str, float]  # query -> nDCG@k (kept for bootstrap CIs)


def evaluate_ranker(engine: SearchEngine, ranker: str,
                    qrels_by_query: QrelsByQuery) -> RankerReport:
    ndcgs: list[float] = []
    rrs: list[float] = []
    precisions: list[float] = []
    per_query: dict[str, float] = {}

    for query, qrels in qrels_by_query.items():
        hits, _ = engine.search(query, ranker=ranker, per_page=TOP_N, now=EVAL_NOW)
        ranking = [h.doc_id for h in hits]
        n = metrics.ndcg_at_k(ranking, qrels, NDCG_K)
        ndcgs.append(n)
        rrs.append(metrics.reciprocal_rank(ranking, qrels))
        precisions.append(metrics.precision_at_k(ranking, qrels, PRECISION_K))
        per_query[query] = n

    return RankerReport(
        ranker=ranker,
        ndcg=metrics.mean(ndcgs),
        mrr=metrics.mean(rrs),
        precision=metrics.mean(precisions),
        per_query_ndcg=per_query,
    )


def evaluate_all(engine: SearchEngine,
                 qrels_by_query: QrelsByQuery) -> list[RankerReport]:
    return [evaluate_ranker(engine, r, qrels_by_query) for r in RANKERS]


def format_report(reports: list[RankerReport], n_queries: int) -> str:
    lines = [
        f"Evaluation over {n_queries} labeled queries "
        f"(nDCG@{NDCG_K}, MRR, P@{PRECISION_K})",
        "",
        f"{'ranker':<18}{'nDCG':>8}{'MRR':>8}{'P@'+str(PRECISION_K):>8}",
        "-" * 42,
    ]
    for r in sorted(reports, key=lambda r: r.ndcg, reverse=True):
        lines.append(f"{r.ranker:<18}{r.ndcg:>8.3f}{r.mrr:>8.3f}{r.precision:>8.3f}")
    return "\n".join(lines)
