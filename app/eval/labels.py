"""Resolve labeled repos against the corpus, injecting any that are missing.

The eval judgments are keyed on full_name. For the eval to be meaningful, every
labeled repo must exist as a document in the corpus so the ranker can (or fail to)
surface it among the real distractors. This module guarantees that:

- already crawled  -> use it as-is (real data)
- real but missing -> fetch it from the GitHub API and upsert (real data)
- synthetic label  -> inject the seed document (these are not real GitHub repos)

`resolve_ids` then maps each labeled full_name to its repo id, which is the same
integer the index uses as a doc_id.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.eval.qrels import SYNTHETIC, labeled_full_names
from app.ingest.normalize import upsert_repository
from app.ingest.seed_data import SEED_REPOS, to_api_shape
from app.models import Repository

API = "https://api.github.com"


def _seed_by_full_name() -> dict[str, dict]:
    return {s["full_name"]: s for s in (to_api_shape(r) for r in SEED_REPOS)}


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def resolve_and_inject(db: Session) -> dict[str, list[str]]:
    """Ensure every labeled full_name exists in the corpus. Returns a report of
    which labels were already present, fetched live, injected from seed, or could
    not be resolved."""
    seeds = _seed_by_full_name()
    report: dict[str, list[str]] = {
        "present": [], "fetched": [], "synthetic": [], "missing": []}

    # follow_redirects: GitHub 301s renamed/transferred repos (e.g. a repo moved
    # to a new org) to their canonical id, so an old-name label needs the redirect
    # followed to reach the real data.
    with httpx.Client(headers=_headers(), timeout=30.0, follow_redirects=True) as client:
        for fn in sorted(labeled_full_names()):
            if db.scalar(select(Repository).where(Repository.full_name == fn)):
                report["present"].append(fn)
                continue
            if fn in SYNTHETIC:
                if fn in seeds:
                    upsert_repository(db, seeds[fn])
                    report["synthetic"].append(fn)
                else:
                    report["missing"].append(fn)
                continue
            resp = client.get(f"{API}/repos/{fn}")
            if resp.status_code == 200:
                raw = resp.json()
                # If the repo was transferred, the response carries the new
                # full_name. Pin identity back to the label so it stays resolvable;
                # all the real stats (stars, description, topics) are kept.
                owner, _, name = fn.partition("/")
                raw["full_name"] = fn
                raw["owner"] = {"login": owner}
                raw["name"] = name
                upsert_repository(db, raw)
                report["fetched"].append(fn)
            elif fn in seeds:  # real fetch failed; fall back to the seed document
                upsert_repository(db, seeds[fn])
                report["synthetic"].append(fn)
            else:
                report["missing"].append(fn)
        db.commit()
    return report


def resolve_ids(db: Session) -> dict[str, int]:
    """Map each labeled full_name to its repo id (== index doc_id)."""
    out: dict[str, int] = {}
    for fn in labeled_full_names():
        rid = db.scalar(select(Repository.id).where(Repository.full_name == fn))
        if rid is not None:
            out[fn] = rid
    return out
