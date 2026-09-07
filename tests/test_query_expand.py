"""Tests for LLM query expansion. The Anthropic client is mocked throughout,
no network calls, no API key needed, keeps CI deterministic and free.
"""
from unittest.mock import MagicMock, patch

import anthropic

from app.search import query_expand


def _fake_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_expand_query_no_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr(query_expand.settings, "anthropic_api_key", "")
    query_expand._client = None
    assert query_expand.expand_query("redis cache") == []


def test_expand_query_empty_query_short_circuits(monkeypatch):
    monkeypatch.setattr(query_expand.settings, "anthropic_api_key", "sk-fake")
    assert query_expand.expand_query("   ") == []


def test_expand_query_parses_terms(monkeypatch):
    monkeypatch.setattr(query_expand.settings, "anthropic_api_key", "sk-fake")
    query_expand._client = None

    with patch("anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response("valkey memcached kv-store")
        terms = query_expand.expand_query("in-memory cache")

    assert terms == ["valkey", "memcached", "kv-store"]
    instance.messages.create.assert_called_once()
    call_kwargs = instance.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"


def test_expand_query_caps_at_six_terms(monkeypatch):
    monkeypatch.setattr(query_expand.settings, "anthropic_api_key", "sk-fake")
    query_expand._client = None

    with patch("anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.return_value = _fake_response("a b c d e f g h")
        terms = query_expand.expand_query("x")

    assert terms == ["a", "b", "c", "d", "e", "f"]


def test_expand_query_api_error_falls_back_to_empty(monkeypatch):
    monkeypatch.setattr(query_expand.settings, "anthropic_api_key", "sk-fake")
    query_expand._client = None

    with patch("anthropic.Anthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create.side_effect = anthropic.APIConnectionError(request=MagicMock())
        terms = query_expand.expand_query("redis")

    assert terms == []
