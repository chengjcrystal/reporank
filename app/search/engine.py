"""Search engine: BM25 relevance + filters + blended re-ranking.

Pure text relevance ignores project quality. The thing that makes this "better
than GitHub default search" is a blended score:

    final = w_text * norm(bm25)
          + w_pop  * norm(log(stars + 1))
          + w_fresh* recency_decay(pushed_at)

Weights are selected by `ranker` variant so we can A/B test them and report
relevance lift (nDCG / CTR) — a first-class ranking-experiment story.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from app.search.bm25 import BM25
from app.search.bm25f import BM25F
from app.search.index import InvertedIndex
from app.search.tokenizer import tokenize


@dataclass(frozen=True)
class RankerConfig:
    """A ranking variant: blend weights + which text-relevance model to use."""
    w_text: float
    w_pop: float
    w_fresh: float
    text_model: str = "bm25"   # "bm25" (flat) or "bm25f" (field-weighted)


# Ranker variants. bm25_only isolates pure relevance; bm25f_v1 swaps the flat
# text model for the field-weighted one so its lift is measurable in eval.
RANKERS: dict[str, RankerConfig] = {
    "bm25_only": RankerConfig(1.0, 0.0, 0.0),
    "bm25_v1": RankerConfig(1.0, 0.35, 0.20),        # default: relevance-led, quality-aware
    "popularity_heavy": RankerConfig(1.0, 0.8, 0.2),
    "bm25f_v1": RankerConfig(1.0, 0.35, 0.20, text_model="bm25f"),
}

_HALF_LIFE_DAYS = 365.0  # a repo untouched for a year keeps ~half its freshness weight


@dataclass
class Filters:
    language: str | None = None
    min_stars: int | None = None
    topics: tuple[str, ...] = ()      # AND semantics: repo must have all
    updated_after: float | None = None  # unix timestamp


@dataclass
class SearchHit:
    doc_id: int
    score: float
    bm25: float


def _recency_decay(pushed_at: float | None, now: float) -> float:
    if not pushed_at:
        return 0.0
    age_days = max(0.0, (now - pushed_at) / 86400.0)
    return 0.5 ** (age_days / _HALF_LIFE_DAYS)


def _normalize(values: dict[int, float]) -> dict[int, float]:
    """Min-max normalize to [0,1]. Empty / flat inputs map to 0."""
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi - lo < 1e-12:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


class SearchEngine:
    def __init__(self, index: InvertedIndex):
        self.index = index
        self.bm25 = BM25(index)
        self.bm25f = BM25F(index)

    def _passes_filters(self, doc_id: int, f: Filters) -> bool:
        meta = self.index.doc_meta.get(doc_id)
        if meta is None:
            return False
        if f.language and (meta.language or "").lower() != f.language.lower():
            return False
        if f.min_stars is not None and meta.stars < f.min_stars:
            return False
        if f.updated_after is not None and (meta.pushed_at or 0) < f.updated_after:
            return False
        if f.topics:
            have = {t.lower() for t in meta.topics}
            if not all(t.lower() in have for t in f.topics):
                return False
        return True

    def search(
        self,
        query: str,
        filters: Filters | None = None,
        ranker: str = "bm25_v1",
        page: int = 1,
        per_page: int = 20,
        now: float | None = None,
    ) -> tuple[list[SearchHit], int]:
        """Return (page_of_hits, total_matches)."""
        filters = filters or Filters()
        now = now or time.time()
        cfg = RANKERS.get(ranker, RANKERS["bm25_v1"])
        w_text, w_pop, w_fresh = cfg.w_text, cfg.w_pop, cfg.w_fresh
        scorer = self.bm25f if cfg.text_model == "bm25f" else self.bm25

        terms = tokenize(query)

        if terms:
            bm25_scores = scorer.score_terms(terms)
            candidates = list(bm25_scores.keys())
        else:
            # Empty query -> browse mode: every doc is a candidate, ranked by
            # popularity + recency only.
            bm25_scores = {}
            candidates = list(self.index.doc_meta.keys())

        # Pre-filter candidate set.
        candidates = [d for d in candidates if self._passes_filters(d, filters)]
        total = len(candidates)
        if total == 0:
            return [], 0

        norm_bm25 = _normalize({d: bm25_scores.get(d, 0.0) for d in candidates}) if bm25_scores else {}
        pop_raw = {d: math.log(self.index.doc_meta[d].stars + 1) for d in candidates}
        norm_pop = _normalize(pop_raw)
        fresh = {d: _recency_decay(self.index.doc_meta[d].pushed_at, now) for d in candidates}

        hits: list[SearchHit] = []
        for d in candidates:
            text_component = norm_bm25.get(d, 0.0)
            final = (
                w_text * text_component
                + w_pop * norm_pop.get(d, 0.0)
                + w_fresh * fresh.get(d, 0.0)
            )
            hits.append(SearchHit(doc_id=d, score=final, bm25=bm25_scores.get(d, 0.0)))

        hits.sort(key=lambda h: h.score, reverse=True)

        start = (page - 1) * per_page
        return hits[start:start + per_page], total
