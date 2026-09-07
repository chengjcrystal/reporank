"""Optional LLM-based query expansion (Anthropic API).

BM25 only matches literal terms, so a natural-language query like "fast web
framework for async apis" scores low on repos whose text just says "fastapi
async". This asks Claude for a handful of related terms (synonyms, common
tech names) to widen the term set before scoring.

Off by default and fails soft: no API key configured, a network error, or an
unexpected response all fall back to the plain query rather than breaking
search. This never touches the BM25/BM25F core (app/search/engine.py) or the
eval-gated ranking path, it only widens the term list handed to it.
"""
from __future__ import annotations

import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5"  # small/fast, appropriate for a short extraction task

_SYSTEM_PROMPT = (
    "You expand search queries for a GitHub repository search engine. "
    "Given a natural-language query, output ONLY a short space-separated list "
    "of additional relevant search terms: synonyms, common library/framework "
    "names, and related technology terms someone might use in a repo "
    "description. Do not repeat words already in the query. Output 3-6 terms, "
    "lowercase, nothing else, no punctuation, no explanation."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic | None:
    global _client
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def expand_query(query: str) -> list[str]:
    """Return extra search terms for `query`, or [] if expansion isn't available."""
    query = (query or "").strip()
    if not query:
        return []

    client = _get_client()
    if client is None:
        return []

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
    except anthropic.APIError as e:
        logger.warning("query expansion failed, falling back to plain query: %s", e)
        return []

    text = next((b.text for b in response.content if b.type == "text"), "")
    terms = [t.strip().lower() for t in text.split() if t.strip()]
    return terms[:6]
