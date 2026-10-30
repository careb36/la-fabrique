"""
The catch-all error handler (``app/exception_handlers.py``).

The 500 says a report was sent only when the support webhook took it, the
incident ticket is published on NATS, and no person's name is in either.
"""

import json

import httpx
import pytest
from exception_handlers import register_exception_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeNATS:
    def __init__(self):
        self.published = []

    async def publish(self, subject, payload):
        self.published.append((subject, json.loads(payload)))


def _app(nats=None):
    app = FastAPI()
    app.state.nats_client = nats
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaput")

    return app


def _get_boom(app):
    return TestClient(app, raise_server_exceptions=False).get("/boom")


def test_without_a_webhook_it_says_the_error_was_logged_and_opens_a_ticket(
    monkeypatch,
):
    monkeypatch.delenv("FABRIQUE_VENDOR_SUPPORT_URL", raising=False)
    nats = _FakeNATS()

    response = _get_boom(_app(nats))

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Fabrique Engine Error. The error has been logged."
    }
    [(subject, ticket)] = nats.published
    assert subject == "system.maintenance.create_ticket"
    assert ticket["description"] == (
        "RuntimeError on GET /boom. No report reached a support webhook."
    )


@pytest.mark.parametrize(("status", "sent"), [(200, True), (503, False)])
def test_it_says_a_report_was_sent_only_when_the_webhook_took_it(
    monkeypatch, status, sent
):
    monkeypatch.setenv("FABRIQUE_VENDOR_SUPPORT_URL", "https://support.example/hook")
    monkeypatch.setenv("FABRIQUE_VENDOR_ID", "acme")
    posted = []

    async def _post(self, url, json=None, timeout=None):
        posted.append(json)
        return httpx.Response(status, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)

    detail = _get_boom(_app()).json()["detail"]

    assert ("sent to support" in detail) is sent
    assert posted[0]["vendor_id"] == "acme"
    assert posted[0]["error_type"] == "RuntimeError"
