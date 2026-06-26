"""SQLAlchemy engine + session setup. DB-agnostic (SQLite locally, Postgres in prod)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# check_same_thread is a SQLite-only quirk; harmless to omit for Postgres.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables. (In a larger project this would be Alembic migrations.)"""
    from app import models  # noqa: F401  ensure models are registered
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
