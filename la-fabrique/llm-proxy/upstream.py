"""
Talking to a provider, and the error that comes back when it cannot answer.

Every provider call funnels through :func:`post_upstream`, so one place decides
what counts as a failure and whether the caller may try another provider. A
timeout is not retried elsewhere: the request's time budget is already spent.
"""

import requests


class UpstreamError(Exception):
    """A provider call that produced no usable answer."""

    def __init__(
        self,
        provider: str,
        model: str,
        status: int | None,
        message: str,
        retriable: bool | None = None,
    ):
        super().__init__(f"{provider} {status} {message}")
        self.provider = provider
        self.model = model
        self.status = status
        self.message = message
        self.attempts: list[dict] = []
        # 429 and 5xx may succeed elsewhere; so may a refused connection.
        if retriable is None:
            retriable = status is None or status == 429 or status >= 500
        self.retriable = retriable

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "message": self.message,
        }


def upstream_message(resp) -> str:
    """The provider's own error text, or the start of the body."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
        if body.get("message"):
            return str(body["message"])
    text_body = (getattr(resp, "text", "") or "").strip()
    return text_body[:300] or f"HTTP {resp.status_code}"


def post_upstream(
    provider: str, model: str, url: str, headers: dict, payload: dict, timeout: float
) -> tuple[int, dict]:
    """POST to a provider; any non-2xx or unreadable body becomes an ``UpstreamError``."""
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout:
        raise UpstreamError(
            provider, model, None, f"timed out after {timeout:.0f}s", retriable=False
        )
    except requests.RequestException as exc:
        raise UpstreamError(provider, model, None, f"request failed: {exc}")
    if not 200 <= resp.status_code < 300:
        raise UpstreamError(provider, model, resp.status_code, upstream_message(resp))
    try:
        body = resp.json()
    except ValueError:
        raise UpstreamError(
            provider, model, resp.status_code, "response body is not JSON", retriable=False
        )
    if not isinstance(body, dict):
        raise UpstreamError(
            provider,
            model,
            resp.status_code,
            "response body is not a JSON object",
            retriable=False,
        )
    if body.get("error"):
        raise UpstreamError(
            provider, model, resp.status_code, upstream_message(resp), retriable=False
        )
    return resp.status_code, body
