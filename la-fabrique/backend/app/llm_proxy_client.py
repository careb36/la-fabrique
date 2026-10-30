"""
LLMProxyClient — HTTP client for the internal LLM proxy service.

The proxy (``llm-proxy/app.py``) centralises all model routing, API-key
management, token-budget enforcement, and Gemini model-catalogue resolution.
This client provides a simple synchronous interface so that backend services
do not need to import or configure LLM SDKs directly.

All methods return a plain dict so callers can inspect ``result.get("error")``
without catching exceptions for common failure paths.
"""

import asyncio
import logging
import os
import time
from typing import Any

import httpx
import requests
from opentelemetry import propagate

logger = logging.getLogger("fabrique-backend")


def _json_body(response: Any) -> dict[str, Any] | None:
    """The proxy's JSON error body (provider, status, message), if it sent one."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - A non-JSON error body is described by its text.
        return None
    return body if isinstance(body, dict) else None


class LLMProxyClient:
    """
    Synchronous HTTP client for the Fabrique LLM proxy with Governance support.

    Args:
        base_url: Base URL of the LLM proxy service (default: ``http://localhost:5100``).
                  Override via the ``LLM_PROXY_URL`` environment variable in production.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("LLM_PROXY_URL", "http://localhost:5100")
        # Has to outlast the proxy's own upstream budget (110 s by default):
        # timing out first makes the proxy look dead while it is still working,
        # and the retry loop then multiplied the wait by three.
        self.timeout = float(os.getenv("LLM_PROXY_TIMEOUT_SECONDS", "150"))
        self.max_retries = int(os.getenv("LLM_PROXY_MAX_RETRIES", "2"))
        self.retry_backoff_sec = float(os.getenv("LLM_PROXY_RETRY_BACKOFF_SEC", "1.0"))

    def _get_headers(
        self, role: str = "Developer", bu_id: int | None = None
    ) -> dict[str, str]:
        """Construct headers for trace propagation and governance."""
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Role": role,
        }
        if bu_id:
            headers["X-Business-Unit-ID"] = str(bu_id)

        # Propagate OpenTelemetry context (TraceParent)
        propagate.inject(headers)
        return headers

    def chat(
        self,
        messages: list,
        model: str = "gemini-pro",
        role: str = "Developer",
        bu_id: int | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a multi-turn chat request to the LLM proxy (OpenAI-compatible).

        ``max_tokens`` is forwarded as-is when given: an answer made of whole
        files does not fit in the provider's default, and the proxy passes the
        payload through unchanged. ``extra`` carries provider-specific switches
        (``chat_template_kwargs``) that the proxy also forwards untouched.
        """
        headers = self._get_headers(role, bu_id)
        payload: dict[str, Any] = {"messages": messages, "model": model}
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if extra:
            payload.update(extra)

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )

                if response.ok:
                    return response.json()

                # Retry transient proxy/provider failures (5xx).
                if response.status_code >= 500 and attempt < self.max_retries:
                    delay = self.retry_backoff_sec * (attempt + 1)
                    logger.warning(
                        "LLM proxy transient error %s for model=%s role=%s (attempt %s/%s), retrying in %.1fs",
                        response.status_code,
                        model,
                        role,
                        attempt + 1,
                        self.max_retries + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                body = response.text[:500]
                logger.error(
                    "LLM proxy request failed: status=%s model=%s role=%s body=%s",
                    response.status_code,
                    model,
                    role,
                    body,
                )
                return {
                    "error": f"HTTP {response.status_code}: {body}",
                    "ok": False,
                    "status_code": response.status_code,
                    "detail": _json_body(response),
                }

            except requests.Timeout as e:
                # Retrying a read timeout only triples the wait: the provider
                # was already given the whole budget for this answer.
                logger.error(f"LLM proxy timed out after {self.timeout:.0f}s: {e}")
                return {"error": str(e), "ok": False, "timed_out": True}

            except requests.RequestException as e:
                if attempt < self.max_retries:
                    delay = self.retry_backoff_sec * (attempt + 1)
                    logger.warning(
                        "LLM proxy request exception for model=%s role=%s (attempt %s/%s): %s; retrying in %.1fs",
                        model,
                        role,
                        attempt + 1,
                        self.max_retries + 1,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                logger.error(f"LLM Proxy call failed after retries: {e}")
                return {"error": str(e), "ok": False}

    async def chat_async(
        self,
        messages: list,
        model: str = "gemini-pro",
        role: str = "Developer",
        bu_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Async variant of ``chat()`` used by LangGraph async nodes.
        """
        headers = self._get_headers(role, bu_id)
        payload = {"messages": messages, "model": model}

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    )

                if response.is_success:
                    result = response.json()
                    if response.headers.get("X-Quota-Warning") == "true":
                        result["quota_warning"] = True
                        result["quota_used"] = response.headers.get("X-Quota-Used")
                        result["quota_limit"] = response.headers.get("X-Quota-Limit")
                    return result

                if response.status_code >= 500 and attempt < self.max_retries:
                    delay = self.retry_backoff_sec * (attempt + 1)
                    logger.warning(
                        "LLM proxy transient async error %s for model=%s role=%s (attempt %s/%s), retrying in %.1fs",
                        response.status_code,
                        model,
                        role,
                        attempt + 1,
                        self.max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                body = response.text[:500]
                logger.error(
                    "LLM proxy async request failed: status=%s model=%s role=%s body=%s",
                    response.status_code,
                    model,
                    role,
                    body,
                )
                return {
                    "error": f"HTTP {response.status_code}: {body}",
                    "ok": False,
                    "status_code": response.status_code,
                    "detail": _json_body(response),
                }

            except httpx.RequestError as e:
                if attempt < self.max_retries:
                    delay = self.retry_backoff_sec * (attempt + 1)
                    logger.warning(
                        "LLM proxy async exception for model=%s role=%s (attempt %s/%s): %s; retrying in %.1fs",
                        model,
                        role,
                        attempt + 1,
                        self.max_retries + 1,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error("LLM Proxy async call failed after retries: %s", e)
                return {"error": str(e), "ok": False}

    def get_available_models(self) -> dict:
        """
        Fetch the live model catalogue from the proxy.

        Returns a dict with keys:
          - ``models``: list of dicts with id, provider, tier, description
          - ``orchestrator``: recommended model for meta-tasks (team suggestion, routing)

        Returns an empty dict on error so callers can fall back gracefully.
        """
        try:
            response = requests.get(f"{self.base_url}/v1/models", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch model catalogue: {e}")
            return {}

    def embed(
        self, text: str, role: str = "Developer", bu_id: int | None = None
    ) -> list | None:
        """Retrieve a dense vector embedding."""
        try:
            headers = self._get_headers(role, bu_id)
            response = requests.post(
                f"{self.base_url}/v1/embeddings",
                json={"input": text},
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            # The proxy returns {"data": [{"embedding": [...]}]} (OpenAI style)
            data = response.json().get("data", [])
            if data:
                return data[0].get("embedding")
            return None
        except requests.RequestException as e:
            logger.error(f"LLM Proxy embedding failed: {e}")
            return None
