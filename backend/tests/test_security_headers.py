"""Tests for security headers on API documentation routes."""

import pytest


def test_health_uses_default_content_security_policy(test_client):
    response = test_client.get("/health")

    assert response.headers["Content-Security-Policy"] == "default-src 'self'"


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_docs_routes_allow_swagger_ui_scripts(test_client, path):
    response = test_client.get(path)
    csp = response.headers["Content-Security-Policy"]

    assert response.status_code == 200
    assert "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'" in csp


def test_redoc_allows_external_scripts_and_google_fonts(test_client):
    response = test_client.get("/redoc")
    csp = response.headers["Content-Security-Policy"]

    assert response.status_code == 200
    assert "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'" in csp
    assert (
        "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com "
        "'unsafe-inline'"
    ) in csp
    assert "font-src https://fonts.gstatic.com" in csp
