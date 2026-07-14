"""Unit tests for the crawler's transient-error retry logic.

These run fully offline against an httpx MockTransport, so no network or token is
needed. `time.sleep` is monkeypatched to a no-op so backoff waits don't slow the
suite.
"""
from __future__ import annotations

import httpx
import pytest

from app.ingest import crawler


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(crawler.time, "sleep", lambda *_a, **_k: None)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_retries_transient_502_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"items": [{"id": 1}]})

    with _client(handler) as client:
        resp = crawler._search_request(client, "language:python stars:50..74", 1, 100)

    assert resp.status_code == 200
    assert calls["n"] == 3  # two 502s retried, third attempt returns 200


def test_gives_up_after_max_retries_and_raises():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            crawler._search_request(client, "q", 1, 100, max_retries=3)


def test_retries_network_error_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"items": []})

    with _client(handler) as client:
        resp = crawler._search_request(client, "q", 1, 100)

    assert resp.status_code == 200
    assert calls["n"] == 2


def test_passes_through_403_for_caller_to_handle():
    """403 (rate limit) is NOT retried here; the caller sleeps to the reset."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})

    with _client(handler) as client:
        resp = crawler._search_request(client, "q", 1, 100)

    assert resp.status_code == 403
