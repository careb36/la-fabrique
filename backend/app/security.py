"""
Security middleware and utilities for the Fabrique Enterprise API.

Provides:
- Rate limiting via slowapi
- Security headers middleware
- CORS configuration
"""

from config import settings
from fastapi import Request
from logging_config import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Rate limiter configuration
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)


from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Strict transport security (HTTPS only)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Content security policy
        if request.url.path in {"/docs", "/redoc", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net "
                "'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net "
                "https://fonts.googleapis.com 'unsafe-inline'; "
                "font-src https://fonts.gstatic.com; "
                "img-src 'self' data: https://fastapi.tiangolo.com; worker-src blob:"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        return response


def setup_security(app):
    """Configure security middleware and rate limiting on the app."""
    from slowapi import _rate_limit_exceeded_handler

    # Add rate limiter to app state
    app.state.limiter = limiter

    # Add rate limit exceeded handler
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Add security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    logger.info("Security middleware configured (rate limiting + security headers)")


def get_cors_origins():
    """Get allowed CORS origins from settings."""
    if settings.CORS_ORIGINS == "*":
        return ["*"]
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]


def check_rate_limit(request: Request):
    """Check if request is within rate limit. Returns True if allowed."""
    # This is a placeholder for custom rate limit logic if needed
    return True
