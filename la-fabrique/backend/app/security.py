"""
Security middleware and utilities for the Fabrique Enterprise API.

Provides:
- Rate limiting via slowapi
- Security headers middleware
- CORS configuration
"""

import os

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


def frame_ancestors() -> list[str]:
    """Origins allowed to embed this UI in an iframe, empty by default.

    The factory ships its own React interface and the desktop assistant's
    dashboard embeds it, which is a *different* origin: `X-Frame-Options: DENY`
    blanked that panel. `SAMEORIGIN` does not help and `ALLOW-FROM` is dead, so
    the caller (run_fusion.py) names the dashboard origins explicitly; without
    that variable the strict default stands.
    """
    raw = os.getenv("FRAME_ANCESTORS", "")
    return [o.strip().rstrip("/") for o in raw.replace(",", " ").split() if o.strip()]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking. An explicit embedder allowlist replaces the
        # blanket DENY, because frame-ancestors is the only header browsers
        # still honour for that.
        ancestors = frame_ancestors()
        if not ancestors:
            response.headers["X-Frame-Options"] = "DENY"

        # XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Strict transport security (HTTPS only)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Content security policy. A route that set its own (the generated
        # project previews, which are sandboxed) keeps it: this middleware is
        # outermost, so overwriting would silently drop the sandbox.
        existing = response.headers.get("Content-Security-Policy")
        if existing:
            csp = existing
        elif request.url.path in {"/docs", "/redoc", "/openapi.json"}:
            csp = (
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net "
                "'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net "
                "https://fonts.googleapis.com 'unsafe-inline'; "
                "font-src https://fonts.gstatic.com; "
                "img-src 'self' data: https://fastapi.tiangolo.com; worker-src blob:"
            )
        else:
            csp = "default-src 'self'"
        if ancestors:
            csp += "; frame-ancestors 'self' " + " ".join(ancestors)
        response.headers["Content-Security-Policy"] = csp

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

    logger.info("Security middleware configured (rate limiting)")


def add_security_headers(app):
    """Attach the headers last so they are the outermost middleware.

    Added in ``setup_security`` they sat *inside* the SPA fallback, and the
    factory's own shell — the one page a browser puts in an iframe — came back
    with no CSP and no X-Frame-Options at all.
    """
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info("Security headers middleware attached (outermost)")


def get_cors_origins():
    """Get allowed CORS origins from settings."""
    if settings.CORS_ORIGINS == "*":
        return ["*"]
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]


def check_rate_limit(request: Request):
    """Check if request is within rate limit. Returns True if allowed."""
    # This is a placeholder for custom rate limit logic if needed
    return True
