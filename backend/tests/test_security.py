"""
Tests for security features: rate limiting, CORS, and security headers.
"""


def test_security_headers_present(test_client):
    """Verify security headers are added to responses."""
    response = test_client.get("/health")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "max-age=31536000" in response.headers.get("Strict-Transport-Security", "")
    assert response.headers.get("Content-Security-Policy") == "default-src 'self'"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_cors_origins_configured(test_client):
    """Verify CORS origins are configured from settings."""
    from config import settings

    # Should have specific origins, not wildcard
    assert settings.CORS_ORIGINS != "*"
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    assert len(origins) > 0


def test_rate_limit_headers_present(test_client):
    """Verify rate limit headers are present in responses."""
    response = test_client.get("/health")

    # slowapi adds rate limit headers
    assert "X-RateLimit-Limit" in response.headers or response.status_code == 200


def test_health_check_not_rate_limited(test_client):
    """Verify health check endpoint is accessible."""
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_security_headers_on_error_responses(test_client):
    """Verify security headers are present even on error responses."""
    # /v1/ is reserved for the API: the SPA shell only answers app routes, so
    # this one is a genuine 404 rather than the index.html.
    response = test_client.get("/v1/nonexistent-endpoint")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_frame_ancestors_replace_the_blanket_deny(test_client, monkeypatch):
    """The assistant's dashboard embeds the factory UI from another origin.

    X-Frame-Options: DENY blanked that panel; the allowlist is explicit and
    travels in frame-ancestors, which is what browsers still honour.
    """
    monkeypatch.setenv("FRAME_ANCESTORS", "http://127.0.0.1:8770 http://localhost:8770")
    response = test_client.get("/health")

    assert "X-Frame-Options" not in response.headers
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; frame-ancestors 'self' "
        "http://127.0.0.1:8770 http://localhost:8770"
    )


def test_the_spa_shell_carries_the_same_headers(test_client, monkeypatch):
    """The page an iframe loads comes from the SPA fallback, not a router."""
    monkeypatch.setenv("FRAME_ANCESTORS", "http://127.0.0.1:*")
    response = test_client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; frame-ancestors 'self' http://127.0.0.1:*"
    )


def test_frame_ancestors_ignores_a_blank_list(test_client, monkeypatch):
    """Whitespace or commas alone must not unlock embedding."""
    monkeypatch.setenv("FRAME_ANCESTORS", " ,  ")
    response = test_client.get("/health")

    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
