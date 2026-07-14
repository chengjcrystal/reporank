"""Command-line entry point for the data + index pipeline.

Usage:
    python -m app.cli init-db
    python -m app.cli seed
    python -m app.cli crawl --language python --min-stars 100 --max-repos 2000
    python -m app.cli build-index
    python -m app.cli stats
    python -m app.cli evaluate
"""
from __future__ import annotations

import argparse

from app.config import settings
from app.db import SessionLocal, init_db
from app.ingest.crawler import crawl
from app.ingest.normalize import upsert_repository
from app.ingest.seed_data import SEED_REPOS, to_api_shape
from app.search.builder import build_index


def cmd_init_db(_args) -> None:
    init_db()
    print(f"Initialized database at {settings.database_url}")


def cmd_seed(_args) -> None:
    init_db()
    db = SessionLocal()
    try:
        for repo in SEED_REPOS:
            upsert_repository(db, to_api_shape(repo))
        db.commit()
        print(f"Seeded {len(SEED_REPOS)} repositories.")
    finally:
        db.close()


def cmd_crawl(args) -> None:
    init_db()
    db = SessionLocal()
    try:
        crawl(db, language=args.language, min_stars=args.min_stars,
              max_repos=args.max_repos, star_step=args.star_step)
    finally:
        db.close()


def cmd_build_index(_args) -> None:
    db = SessionLocal()
    try:
        index, stats = build_index(db)
        index.save(settings.index_path)
    finally:
        db.close()
    print(f"Index built and saved to {settings.index_path}")
    for k, v in stats.items():
        print(f"  {k:14} {v}")


def cmd_stats(_args) -> None:
    from app.models import Repository, SearchLog
    db = SessionLocal()
    try:
        repos = db.query(Repository).count()
        searches = db.query(SearchLog).count()
        print(f"repositories: {repos}")
        print(f"search_logs:  {searches}")
    finally:
        db.close()


def cmd_evaluate(_args) -> None:
    from app.eval import evaluate
    from app.eval.gate import load_frozen_engine, load_frozen_qrels

    engine = load_frozen_engine()
    if engine is None:
        print("Frozen eval index missing. Run: python -m app.cli freeze-eval")
        return
    qrels = load_frozen_qrels()
    reports = evaluate.evaluate_all(engine, qrels)
    print(evaluate.format_report(reports, len(qrels)))


def cmd_freeze_eval(_args) -> None:
    from app.eval.gate import freeze

    db = SessionLocal()
    try:
        summary = freeze(db)
    finally:
        db.close()
    print("label injection:", {k: len(v) for k, v in summary["inject"].items()})
    print(f"labels resolved:  {summary['labels_resolved']}")
    print(f"frozen index:     {summary['build']['documents']} docs -> "
          f"{settings.eval_index_path}")
    print("baseline (nDCG@10 with bootstrap 95% CI):")
    for r, v in summary["baseline"]["rankers"].items():
        print(f"  {r:18} nDCG={v['ndcg']:.3f}  CI95={v['ndcg_ci95']}  "
              f"MRR={v['mrr']:.3f}  P@5={v['precision']:.3f}")


def cmd_eval_gate(_args) -> None:
    from app.eval.gate import run_gate

    res = run_gate()
    status = "PASS" if res["passed"] else "FAIL"
    print(f"[{status}] ranker={res['ranker']} nDCG@10={res['ndcg']:.4f} "
          f"(baseline {res['baseline']:.4f}, floor {res['floor']:.4f} "
          f"= baseline-{res['margin']}, CI95={res['ndcg_ci95']}, "
          f"n={res['n_queries']} queries)")
    if not res["passed"]:
        raise SystemExit("ranking regression: nDCG fell below the floor")


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Repo Search Engine pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    sub.add_parser("seed").set_defaults(func=cmd_seed)

    p_crawl = sub.add_parser("crawl")
    p_crawl.add_argument("--language", default=None)
    p_crawl.add_argument("--min-stars", type=int, default=100)
    p_crawl.add_argument("--max-repos", type=int, default=2000)
    p_crawl.add_argument("--star-step", type=int, default=50)
    p_crawl.set_defaults(func=cmd_crawl)

    sub.add_parser("build-index").set_defaults(func=cmd_build_index)
    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("evaluate").set_defaults(func=cmd_evaluate)
    sub.add_parser("freeze-eval").set_defaults(func=cmd_freeze_eval)
    sub.add_parser("eval-gate").set_defaults(func=cmd_eval_gate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
