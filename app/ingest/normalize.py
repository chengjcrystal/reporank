"""Turn a raw GitHub API repo object into our persisted/upserted form."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Repository, Topic


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # GitHub returns ISO-8601 with trailing 'Z'.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_search_document(name: str, description: str | None,
                          topics: list[str], readme: str | None) -> str:
    """Denormalized text blob the indexer consumes.

    The repo name is repeated to give it a light field boost (a poor-man's
    field weighting until/unless we move to BM25F).
    """
    parts = [name, name, description or "", " ".join(topics)]
    if readme:
        parts.append(readme[:4000])  # cap README so the index stays lean
    return "\n".join(p for p in parts if p)


def upsert_repository(db: Session, raw: dict, readme: str | None = None) -> Repository:
    """Idempotent insert-or-update keyed on GitHub repo id."""
    topics = raw.get("topics") or []
    owner = (raw.get("owner") or {}).get("login", "")
    name = raw.get("name", "")
    description = raw.get("description")

    repo = db.get(Repository, raw["id"])
    if repo is None:
        repo = Repository(id=raw["id"])
        db.add(repo)

    repo.full_name = raw.get("full_name", f"{owner}/{name}")
    repo.owner = owner
    repo.name = name
    repo.description = description
    repo.primary_language = raw.get("language")
    repo.stars = raw.get("stargazers_count", 0)
    repo.forks = raw.get("forks_count", 0)
    repo.open_issues = raw.get("open_issues_count", 0)
    repo.watchers = raw.get("watchers_count", 0)
    repo.license = (raw.get("license") or {}).get("spdx_id") if raw.get("license") else None
    repo.homepage = raw.get("homepage")
    repo.html_url = raw.get("html_url", "")
    repo.is_fork = raw.get("fork", False)
    repo.is_archived = raw.get("archived", False)
    repo.pushed_at = _parse_dt(raw.get("pushed_at"))
    repo.created_at = _parse_dt(raw.get("created_at"))
    repo.updated_at = _parse_dt(raw.get("updated_at"))
    if readme is not None:
        repo.readme_text = readme[:8000]

    # Topics (many-to-many, deduped via get-or-create).
    repo.topics = [_get_or_create_topic(db, t) for t in topics]

    repo.search_document = build_search_document(name, description, topics, repo.readme_text)
    return repo


def _get_or_create_topic(db: Session, name: str) -> Topic:
    existing = db.query(Topic).filter(Topic.name == name).one_or_none()
    if existing:
        return existing
    topic = Topic(name=name)
    db.add(topic)
    db.flush()
    return topic
