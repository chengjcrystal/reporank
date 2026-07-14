"""Hand-labeled relevance judgments (qrels) for offline ranking evaluation.

Judgments are keyed on **repo full_name** (owner/name), not on a fragile internal
id, so the same labels apply against the full crawled corpus: the graded repos sit
among 157k real distractors and the ranker has to surface them. Grades:

    3 = ideal hit, exactly what the query is asking for
    2 = strongly relevant
    1 = marginally relevant / topically adjacent
    (absent = irrelevant, graded 0)

Graded (not binary) judgments are deliberate: they let nDCG reward a ranker for
putting the *best* match first, which is the whole point of comparing variants.

Some labeled repos are not real GitHub repos (they were authored for the original
seed demo: starters, tutorials, a renamed detectron). Those are marked in
SYNTHETIC and injected into the corpus from the seed data so the labels still have
a document to match; the rest are real repos, present in or injected into the
crawl. See `app/eval/labels.py` for the resolve/inject logic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabeledQuery:
    query: str
    judgments: dict[str, int]  # full_name -> grade


QRELS: list[LabeledQuery] = [
    LabeledQuery("distributed systems projects", {
        "etcd-io/etcd": 3,
        "apache/kafka": 3,
        "kubernetes/kubernetes": 3,
        "tikv/tikv": 3,
        "prometheus/prometheus": 2,
        "minio/minio": 2,
        "tikv/raft-rs": 2,
        "tutorials/distributed-systems-101": 2,
        "celery/celery": 1,
        "redis/redis": 1,
    }),
    LabeledQuery("fastapi postgresql applications", {
        "fullstack-demo/fastapi-postgres-starter": 3,
        "fastapi-users/fastapi-users": 3,
        "tiangolo/fastapi": 2,
        "encode/django-rest-framework": 2,
        "sqlalchemy/sqlalchemy": 1,
    }),
    LabeledQuery("computer vision with deployment", {
        "ultralytics/yolov5": 3,
        "roboflow/supervision": 3,
        "detectron/detectron2": 2,
        "opencv/opencv": 2,
        "huggingface/transformers": 1,
        "old-projects/legacy-image-classifier": 1,
    }),
    LabeledQuery("in memory key value store", {
        "redis/redis": 3,
        "dragonflydb/dragonfly": 3,
        "valkey-io/valkey": 3,
        "etcd-io/etcd": 2,
        "tikv/tikv": 2,
    }),
    LabeledQuery("beginner friendly backend projects", {
        "tutorials/distributed-systems-101": 3,
        "fullstack-demo/fastapi-postgres-starter": 3,
        "learn-backend/build-your-own-redis": 2,
    }),
    LabeledQuery("monitoring and metrics", {
        "prometheus/prometheus": 3,
        "grafana/grafana": 3,
    }),
    LabeledQuery("raft consensus algorithm", {
        "tikv/raft-rs": 3,
        "etcd-io/etcd": 2,
        "tikv/tikv": 2,
        "tutorials/distributed-systems-101": 1,
    }),
    LabeledQuery("python web framework", {
        "tiangolo/fastapi": 3,
        "encode/django-rest-framework": 3,
        "fastapi-users/fastapi-users": 1,
    }),
    LabeledQuery("react frontend library", {
        "facebook/react": 3,
        "vercel/next.js": 3,
    }),
    LabeledQuery("object storage", {
        "minio/minio": 3,
    }),
]

# Labeled repos that are not real GitHub repositories (authored for the seed demo).
# They are injected into the corpus from the seed data so the labels resolve.
SYNTHETIC: set[str] = {
    "fullstack-demo/fastapi-postgres-starter",
    "tutorials/distributed-systems-101",
    "learn-backend/build-your-own-redis",
    "old-projects/legacy-image-classifier",
    "detectron/detectron2",  # the real one is facebookresearch/detectron2
}


def labeled_full_names() -> set[str]:
    names: set[str] = set()
    for lq in QRELS:
        names.update(lq.judgments)
    return names
