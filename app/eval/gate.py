"""Ranking-regression gate: score nDCG against a frozen index and fail on drops.

Design (deliberate, given a 10-query judgment set):

- The gate scores against a FROZEN index snapshot (`eval_index.pkl`) built over the
  full crawled corpus with every labeled repo embedded. So the ranker has to
  surface the labels past 150k+ real distractors, and the measurement is
  reproducible run to run.
- Judgments live in `qrels.py` keyed on full_name; `freeze()` resolves them to
  doc_ids against the frozen index and writes `frozen_qrels.json` so the gate is
  independent of the live DB.
- We report a bootstrap 95% CI over the queries, but we do NOT gate on it: at
  n=10 the CI is wide and would flap. The gate is on the point estimate with a
  fixed margin, and the coarseness is documented rather than hidden.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.eval import evaluate
from app.eval.labels import resolve_and_inject, resolve_ids
from app.eval.qrels import QRELS
from app.search.engine import RANKERS, SearchEngine
from app.search.index import InvertedIndex

_HERE = Path(__file__).parent
FROZEN_QRELS_PATH = _HERE / "frozen_qrels.json"
BASELINE_PATH = _HERE / "baseline.json"

GATED_RANKER = "bm25f_v1"
MARGIN = 0.05          # allowed drop from baseline before the gate fails
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 0


def bootstrap_ci(values: list[float], alpha: float = 0.05,
                 n_boot: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED
                 ) -> tuple[float, float, float]:
    """Return (point_estimate, ci_low, ci_high): the mean, and a percentile
    bootstrap CI over resampled queries. Deterministic given the seed."""
    n = len(values)
    point = sum(values) / n if n else 0.0
    if n == 0:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        resample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(resample) / n)
    means.sort()
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[int((1 - alpha / 2) * n_boot)]
    return point, lo, hi


def load_frozen_qrels() -> evaluate.QrelsByQuery:
    raw = json.loads(FROZEN_QRELS_PATH.read_text())
    return {q: {int(doc_id): float(g) for doc_id, g in judged.items()}
            for q, judged in raw.items()}


def _per_query_ndcg(engine: SearchEngine, ranker: str,
                    qrels: evaluate.QrelsByQuery) -> list[float]:
    report = evaluate.evaluate_ranker(engine, ranker, qrels)
    return [report.per_query_ndcg[q] for q in qrels]


def freeze(db: Session) -> dict:
    """Inject labels, build + save the frozen eval index, and write the frozen
    qrels and the baseline. Returns a summary dict."""
    inject_report = resolve_and_inject(db)

    from app.search.builder import build_index
    index, build_stats = build_index(db)
    index.save(settings.eval_index_path)

    ids = resolve_ids(db)
    frozen = {}
    for lq in QRELS:
        frozen[lq.query] = {str(ids[fn]): g
                            for fn, g in lq.judgments.items() if fn in ids}
    FROZEN_QRELS_PATH.write_text(json.dumps(frozen, indent=2, sort_keys=True))

    qrels = load_frozen_qrels()
    engine = SearchEngine(index)
    baseline = {"gated_ranker": GATED_RANKER, "margin": MARGIN,
                "n_queries": len(qrels), "corpus_docs": index.N, "rankers": {}}
    for ranker in RANKERS:
        rep = evaluate.evaluate_ranker(engine, ranker, qrels)
        point, lo, hi = bootstrap_ci([rep.per_query_ndcg[q] for q in qrels])
        baseline["rankers"][ranker] = {
            "ndcg": round(point, 4), "mrr": round(rep.mrr, 4),
            "precision": round(rep.precision, 4),
            "ndcg_ci95": [round(lo, 4), round(hi, 4)]}
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True))

    return {"inject": inject_report, "build": build_stats,
            "labels_resolved": len(ids), "baseline": baseline}


def load_frozen_engine() -> SearchEngine | None:
    if not Path(settings.eval_index_path).exists():
        return None
    return SearchEngine(InvertedIndex.load(settings.eval_index_path))


def run_gate() -> dict:
    """Score the gated ranker against the frozen baseline. Returns a result dict
    with `passed`. Raises FileNotFoundError if the frozen index is absent."""
    engine = load_frozen_engine()
    if engine is None:
        raise FileNotFoundError(
            f"Frozen eval index missing at {settings.eval_index_path}. "
            f"Run: python -m app.cli freeze-eval")
    baseline = json.loads(BASELINE_PATH.read_text())
    qrels = load_frozen_qrels()

    point, lo, hi = bootstrap_ci(_per_query_ndcg(engine, GATED_RANKER, qrels))
    base = baseline["rankers"][GATED_RANKER]["ndcg"]
    floor = base - MARGIN
    return {
        "ranker": GATED_RANKER,
        "ndcg": round(point, 4),
        "ndcg_ci95": [round(lo, 4), round(hi, 4)],
        "baseline": base,
        "floor": round(floor, 4),
        "margin": MARGIN,
        "n_queries": len(qrels),
        "passed": point >= floor,
    }
