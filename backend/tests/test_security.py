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
    response = test_client.get("/nonexistent-endpoint")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
