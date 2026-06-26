"""Hand-labeled relevance judgments (qrels) for offline ranking evaluation.

Each entry pairs a query with graded relevance judgments over the seed corpus
(seed_data.py, doc_id == repo id). Grades:

    3 = ideal hit, exactly what the query is asking for
    2 = strongly relevant
    1 = marginally relevant / topically adjacent
    (absent = irrelevant, graded 0)

Graded (not binary) judgments are deliberate: they let nDCG reward a ranker for
putting the *best* match first, which is the whole point of comparing variants.
Judgments are over the 30-repo seed set so `evaluate` runs offline with no token.
Doc-id comments name the repo so the labels stay auditable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabeledQuery:
    query: str
    judgments: dict[int, int]  # doc_id -> grade


QRELS: list[LabeledQuery] = [
    LabeledQuery("distributed systems projects", {
        2: 3,   # etcd
        3: 3,   # kafka
        18: 3,  # kubernetes
        4: 3,   # tikv
        20: 2,  # prometheus
        22: 2,  # minio
        5: 2,   # raft-rs
        24: 2,  # distributed-systems-101
        25: 1,  # celery
        1: 1,   # redis
    }),
    LabeledQuery("fastapi postgresql applications", {
        9: 3,   # fastapi-postgres-starter
        28: 3,  # fastapi-users
        6: 2,   # fastapi
        7: 2,   # django-rest-framework (rest + postgres)
        8: 1,   # sqlalchemy
    }),
    LabeledQuery("computer vision with deployment", {
        12: 3,  # yolov5 (export / deployment)
        13: 3,  # supervision (production CV)
        29: 2,  # detectron2
        11: 2,  # opencv
        15: 1,  # transformers
        30: 1,  # legacy-image-classifier
    }),
    LabeledQuery("in memory key value store", {
        1: 3,   # redis
        26: 3,  # dragonfly
        27: 3,  # valkey
        2: 2,   # etcd
        4: 2,   # tikv
    }),
    LabeledQuery("beginner friendly backend projects", {
        24: 3,  # distributed-systems-101
        9: 3,   # fastapi-postgres-starter
        23: 2,  # build-your-own-redis
    }),
    LabeledQuery("monitoring and metrics", {
        20: 3,  # prometheus
        19: 3,  # grafana
    }),
    LabeledQuery("raft consensus algorithm", {
        5: 3,   # raft-rs
        2: 2,   # etcd
        4: 2,   # tikv
        24: 1,  # distributed-systems-101
    }),
    LabeledQuery("python web framework", {
        6: 3,   # fastapi
        7: 3,   # django-rest-framework
        28: 1,  # fastapi-users
    }),
    LabeledQuery("react frontend library", {
        16: 3,  # react
        17: 3,  # next.js
    }),
    LabeledQuery("object storage", {
        22: 3,  # minio
    }),
]
