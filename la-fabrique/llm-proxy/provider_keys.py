"""
Startup validation of the provider keys.

One block per provider, and they differ only in how the provider reports a
bad key: Gemini answers ``GET /models``, DeepSeek and Qwen ``POST
/chat/completions``, Nebius ``GET /models`` again. A network failure is not an
invalid key, so it is logged and the proxy still starts; only a provider that
answers 401/403 is fatal.
"""

import logging

import requests

logger = logging.getLogger(__name__)


def validate_api_keys(keys: dict[str, str], urls: dict[str, str]) -> list[str]:
    """Return the invalid keys' provider names, logging one line per provider."""
    errors = []
    for provider, key in keys.items():
        if not key:
            logger.warning(f"{provider.upper()}_API_KEY is not set")
            continue
        try:
            status, body = _probe(provider, key, urls[provider])
        except Exception as exc:
            logger.warning(f"Could not validate {provider} API key: {exc}")
            continue
        if status in (401, 403) or "invalid_api_key" in body:
            errors.append(f"{provider.upper()}_API_KEY is invalid")
        else:
            logger.info(f"{provider} API key validated successfully")

    if errors:
        for err in errors:
            logger.error(f"API KEY VALIDATION FAILED: {err}")
        logger.error(
            "Some API keys are invalid. Agent tasks will fail until keys are corrected."
        )
    return errors


def _probe(provider: str, key: str, base_url: str) -> tuple[int, str]:
    """Ask the provider to authenticate: the cheapest endpoint that rejects a bad key."""
    if provider == "gemini":
        resp = requests.get(
            f"{base_url}/models", headers={"x-goog-api-key": key}, timeout=10
        )
    elif provider in ("deepseek", "qwen"):
        model = "deepseek-flash" if provider == "deepseek" else "qwen3.6-flash"
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=10,
        )
    else:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
    return resp.status_code, resp.text
