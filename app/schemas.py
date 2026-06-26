"""Pydantic response models — typed API contracts (and free OpenAPI docs)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RepoResult(BaseModel):
    id: int
    full_name: str
    description: str | None
    stars: int
    forks: int
    language: str | None
    topics: list[str]
    pushed_at: datetime | None
    html_url: str
    score: float          # blended ranking score (exposed for transparency)
    bm25: float           # raw text-relevance component


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    per_page: int
    latency_ms: float
    ranker: str
    results: list[RepoResult]


class SuggestResponse(BaseModel):
    query: str
    suggestions: list[str]


class FiltersResponse(BaseModel):
    languages: list[str]
    topics: list[str]


class ClickEvent(BaseModel):
    query: str
    repo_id: int
    ranker: str | None = None
