"""
Which models a given provider currently serves, and which provider a model id
belongs to.

A model id names its provider by prefix, and the id must also be in that
provider's fetched catalogue before a request is sent anywhere. A mistyped or
retired id fails here instead of being forwarded to a provider that never
served it.

The catalogue sets themselves live in this module; ``app`` reaches them
through the functions below so the tests that swap a set out still see the
module-level name they patch.
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

# Tier classification rules applied in order — first match wins.
# Tuple: (substring_tests, tier_name, description)
_TIER_RULES: list[tuple[list[str], str, str]] = [
    (["preview"], "preview", "Experimental preview — may be unstable"),
    (["flash-lite", "lite"], "fast", "Lightweight, fastest responses"),
    (["2.5-pro", "3-pro"], "strategic", "Deep reasoning, architecture, stakeholder decisions"),
    (["pro"], "strategic", "Deep reasoning, architecture, stakeholder decisions"),
    (["flash"], "balanced", "Fast reasoning, coordination, reviews"),
    (["coder"], "code", "Specialised code generation & refactoring (~10x cheaper)"),
    (["chat"], "balanced", "General-purpose reasoning and conversation"),
]

# Deprecated Gemini ids mapped to their working equivalents.
GEMINI_ALIASES = {
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.5-pro": "gemini-3.1-pro-preview",
    "gemini-2.0-flash": "gemini-3.8-flash",
}

# Models that are no longer available to new users (Google deprecation).
GEMINI_DEPRECATED = {
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
}

# Nebius ids carry a vendor segment ("nvidia/…", "meta-llama/…"), hence the
# vendor/ prefix rather than a bare model-name prefix.
PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-", "gemma-"),
    "deepseek": ("deepseek-",),
    "qwen": ("qwen", "qwq-", "qvq-"),
    "nebius": ("nvidia/", "meta-llama/", "mistralai/", "deepseek-ai/", "qwen/", "google/"),
}


def classify_model(model_id: str) -> tuple[str, str]:
    """Return (tier, description) for a model ID based on naming conventions."""
    lower = model_id.lower()
    for substrings, tier, desc in _TIER_RULES:
        if any(s in lower for s in substrings):
            return tier, desc
    return "balanced", "General-purpose model"


def provider_for_model(model_id: str) -> str | None:
    """The provider whose prefix *model_id* carries, or ``None``."""
    lower = (model_id or "").strip().lower()
    for provider, prefixes in PROVIDER_PREFIXES.items():
        if lower.startswith(prefixes):
            return provider
    return None


def fetch_model_ids(provider: str, key: str, base_url: str) -> set[str]:
    """The provider's live chat-capable model ids.

    Raises whatever the request raises: the caller decides whether a failed
    refresh is fatal (it is not) and keeps the previous catalogue.
    """
    if provider == "gemini":
        resp = requests.get(
            f"{base_url}/models", headers={"x-goog-api-key": key}, timeout=10
        )
        resp.raise_for_status()
        return {
            m["name"].split("/")[-1]
            for m in resp.json().get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        }

    resp = requests.get(
        f"{base_url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10
    )
    resp.raise_for_status()
    skip = {
        "qwen": ("image", "audio", "video", "tts", "realtime", "wan", "embedding"),
        "nebius": ("embedding", "rerank"),
    }.get(provider, ())
    return {
        m.get("id")
        for m in resp.json().get("data", [])
        if m.get("id") and not any(k in m.get("id", "").lower() for k in skip)
    }
