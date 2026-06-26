"""ORM models. Postgres is the source of truth; the search index is derived from these."""
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Table, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Many-to-many: repositories <-> topics
repository_topics = Table(
    "repository_topics",
    Base.metadata,
    Column("repository_id", BigInteger, ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", Integer, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
)


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    repositories: Mapped[list["Repository"]] = relationship(
        secondary=repository_topics, back_populates="topics"
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # GitHub repo id (stable)
    full_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    owner: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    stars: Mapped[int] = mapped_column(Integer, default=0, index=True)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    watchers: Mapped[int] = mapped_column(Integer, default=0)

    license: Mapped[str | None] = mapped_column(String, nullable=True)
    homepage: Mapped[str | None] = mapped_column(String, nullable=True)
    html_url: Mapped[str] = mapped_column(String)
    readme_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Denormalized text the indexer consumes (name + desc + topics + readme).
    search_document: Mapped[str | None] = mapped_column(Text, nullable=True)

    topics: Mapped[list[Topic]] = relationship(
        secondary=repository_topics, back_populates="repositories"
    )

    def topic_names(self) -> list[str]:
        return [t.name for t in self.topics]


class CrawlState(Base):
    """Makes ingestion resumable and idempotent."""
    __tablename__ = "crawl_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String)         # e.g. "stars:100..200 language:python"
    last_page: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|running|complete|error
    repos_fetched: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SearchLog(Base):
    """Powers the analytics dashboard AND offline ranking evaluation (CTR / MRR)."""
    __tablename__ = "search_logs"
    # SQLite only auto-increments INTEGER PRIMARY KEY, not BIGINT.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    query: Mapped[str] = mapped_column(String, index=True)
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Integer, default=0)
    ranker_variant: Mapped[str | None] = mapped_column(String, nullable=True)
    clicked_repo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
