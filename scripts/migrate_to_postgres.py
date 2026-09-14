"""One-time copy of the local SQLite corpus into a hosted Postgres database.

Run this once against the local ghsearch.db to seed a production Postgres
instance, so the live deploy doesn't need to re-crawl GitHub. Only Topic,
Repository, and the repository_topics join table are copied; search_logs and
crawl_state are local dev history and start fresh in production.

Run from the repo root:
    .venv/bin/python scripts/migrate_to_postgres.py --target postgresql+psycopg://...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Repository, Topic, repository_topics

CHUNK = 1000


def copy_table(src_session, dst_conn, table, order_col=None):
    stmt = select(table)
    if order_col is not None:
        stmt = stmt.order_by(order_col)
    rows = src_session.execute(stmt).all()
    for i in range(0, len(rows), CHUNK):
        batch = [dict(r._mapping) for r in rows[i:i + CHUNK]]
        if batch:
            dst_conn.execute(insert(table), batch)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="sqlite:///./ghsearch.db")
    parser.add_argument("--target", required=True, help="destination Postgres DATABASE_URL")
    args = parser.parse_args()

    src_engine = create_engine(args.source, future=True)
    dst_engine = create_engine(args.target, future=True)

    from app import models  # noqa: F401  ensure models are registered
    Base.metadata.create_all(dst_engine)

    SrcSession = sessionmaker(bind=src_engine, future=True)
    with SrcSession() as src, dst_engine.begin() as dst:
        n = copy_table(src, dst, Topic.__table__, Topic.id)
        print(f"copied {n} topics")

        n = copy_table(src, dst, Repository.__table__, Repository.id)
        print(f"copied {n} repositories")

        n = copy_table(src, dst, repository_topics)
        print(f"copied {n} repo-topic links")

    print("done")


if __name__ == "__main__":
    main()
