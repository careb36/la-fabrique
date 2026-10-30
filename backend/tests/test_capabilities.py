"""Tests for the public ``GET /v1/capabilities`` endpoint."""

from unittest.mock import MagicMock

import pytest
from config import settings

from app.main import app


@pytest.fixture
def default_settings(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_GRAPH_ENABLED", False)
    monkeypatch.setattr(settings, "GITHUB_TOKEN", None)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", None)
    monkeypatch.setattr(settings, "SUPPORT_AGENT_ENABLED", False)
    monkeypatch.setattr(app.state, "memory_client", None, raising=False)


def test_default_capabilities(test_client, default_settings):
    response = test_client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "agent_graph": False,
        "memory": False,
        "github": False,
        "auth_required": True,
        "support_agent": False,
        "public_api_url": None,
    }


def test_agent_graph_enabled(test_client, default_settings, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_GRAPH_ENABLED", True)

    response = test_client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["agent_graph"] is True


def test_memory_follows_memory_client(test_client, default_settings):
    # Assign directly: monkeypatch cannot restore a Starlette State key that was
    # written by the lifespan, so its teardown raises KeyError.
    previous = app.state.memory_client
    try:
        app.state.memory_client = MagicMock()
        assert test_client.get("/v1/capabilities").json()["memory"] is True

        app.state.memory_client = None
        assert test_client.get("/v1/capabilities").json()["memory"] is False
    finally:
        app.state.memory_client = previous


def test_github_token_enables_github(test_client, default_settings, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_test")

    response = test_client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["github"] is True


def test_public_when_auth_required(test_client, default_settings):
    # Sanity check: the same client is rejected on a protected route.
    assert test_client.get("/v1/agent_runs?company_id=1").status_code == 401

    response = test_client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["auth_required"] is True


def test_public_api_url_is_reported_without_trailing_slash(
    test_client, default_settings, monkeypatch
):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://fabrique.example.com/")

    assert test_client.get("/v1/capabilities").json()["public_api_url"] == (
        "https://fabrique.example.com"
    )
