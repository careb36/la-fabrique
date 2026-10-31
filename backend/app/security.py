"""
Security middleware and utilities for the Fabrique Enterprise API.

Provides:
- Rate limiting via slowapi
- Security headers middleware
- CORS configuration
"""

from config import settings
from fastapi import Request
from limits import parse as parse_limit
from logging_config import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

# Rate limiter configuration
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)


from starlette.middleware.base import BaseHTTPMiddleware


def apply_security_headers(path: str, response):
    """Set the security headers on *response* for a request to *path*.

    The middleware calls it on every response; the 500 handler calls it too,
    because Starlette sends an unhandled error from outside every middleware.
    With ``SECURITY_HEADERS_ENABLED`` off the response is left as it is.
    """
    if not settings.SECURITY_HEADERS_ENABLED:
        return response

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
    if path in {"/docs", "/redoc", "/openapi.json"}:
        csp = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net "
            "'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net "
            "https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https://fastapi.tiangolo.com; worker-src blob:"
        )
    else:
        csp = "default-src 'self'"
    response.headers["Content-Security-Policy"] = csp

    # Referrer policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Permissions policy
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        return apply_security_headers(request.url.path, response)


# The Glassroom stream is an EventSource that reconnects on its own, so it is
# never refused. Health, metrics, the docs and the UI's files are not under
# /v1/ and are never limited either.
RATE_LIMIT_EXEMPT = {"/v1/glassroom/stream"}
_DEFAULT_LIMIT = parse_limit(settings.RATE_LIMIT_DEFAULT)
_LOCAL_STORAGE = settings.RATE_LIMIT_STORAGE_URI.startswith("memory://")


def is_rate_limited(path: str) -> bool:
    """Whether a request to *path* counts against ``RATE_LIMIT_DEFAULT``."""
    return path.startswith("/v1/") and path not in RATE_LIMIT_EXEMPT


class DefaultRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply ``RATE_LIMIT_DEFAULT`` to every API request, per client address.

    slowapi's own middleware finds the route before counting, and FastAPI no
    longer flattens included routers into ``app.routes``, so it found none and
    limited nothing. This counts by path instead, in the limiter's storage;
    the sign-in routes still carry their own, tighter limit on top.
    """

    async def dispatch(self, request: Request, call_next):
        if limiter.enabled and is_rate_limited(request.url.path):
            key = get_remote_address(request)
            if _LOCAL_STORAGE:
                allowed = limiter._limiter.hit(_DEFAULT_LIMIT, "default", key)
            else:
                # A remote store (Redis, Memcached) answers over the network:
                # wait for it off the event loop, not on it.
                allowed = await run_in_threadpool(
                    limiter._limiter.hit, _DEFAULT_LIMIT, "default", key
                )
            if not allowed:
                return JSONResponse(
                    {"error": f"Rate limit exceeded: {settings.RATE_LIMIT_DEFAULT}"},
                    status_code=429,
                )
        return await call_next(request)


def setup_security(app):
    """Configure security middleware and rate limiting on the app."""
    from slowapi import _rate_limit_exceeded_handler

    # Add rate limiter to app state
    app.state.limiter = limiter

    # Add rate limit exceeded handler
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(DefaultRateLimitMiddleware)

    logger.info("Security middleware configured (rate limiting)")


def add_security_headers(app):
    """Attach the headers last so they are the outermost middleware.

    Added in ``setup_security`` they sat *inside* the SPA fallback, and the
    factory's own shell — the one page a browser puts in an iframe — came back
    with no CSP and no X-Frame-Options at all.
    """
    if not settings.SECURITY_HEADERS_ENABLED:
        logger.warning(
            "SECURITY_HEADERS_ENABLED is off: responses carry no security headers"
        )
        return
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info("Security headers middleware attached (outermost)")


def get_cors_origins():
    """Get allowed CORS origins from settings."""
    if settings.CORS_ORIGINS == "*":
        return ["*"]
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
