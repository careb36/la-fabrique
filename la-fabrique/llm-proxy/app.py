"""
LLM Proxy - Enterprise Multi-Model Gateway v2.0 (Phase 4)

Governance-ready proxy that routes requests to Gemini, DeepSeek or Qwen with:
- **Distributed Tracing**: OpenTelemetry instrumentation.
- **Explicit Model Routing**: a model id picks its provider by prefix and must
  be in that provider's catalogue (refreshed hourly); anything else is a 400
  ``unknown_model``.  Responses carry ``served_model``.
- **Quota Enforcement**: Persistent token tracking per Business Unit via PostgreSQL.
"""

import os
import time
import threading
import logging
from flask import Flask, request, jsonify
import requests
from sqlalchemy import create_engine, text
import upstream
from catalogue import GEMINI_ALIASES as _GEMINI_ALIASES
from catalogue import GEMINI_DEPRECATED as _GEMINI_DEPRECATED
from catalogue import classify_model as _classify_model
from catalogue import fetch_model_ids, open_model_tier
from provider_keys import validate_api_keys
from usage import fallback_embedding as _fallback_embedding
from usage import estimated_usage, openai_reported_count, openai_text, reported_count, with_usage

# --- OpenTelemetry ---
from tracing import instrument
from opentelemetry.trace import StatusCode

app = Flask(__name__)


_tracer = instrument(app)

# --- Config & Logging ---
def _env(name: str, default: str = "") -> str:
    """One env value, trimmed.

    A ``.env`` edited on Windows ends its lines with CRLF, and a ``\r`` inside
    an API key makes the provider reject every request ("invalid header
    value") while the key itself is fine. Trimming here is what keeps a Windows
    checkout working.
    """
    return os.getenv(name, default).strip()


GEMINI_API_KEY = _env("GEMINI_API_KEY")
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY")
QWEN_API_KEY = _env("QWEN_API_KEY")
NEBIUS_API_KEY = _env("NEBIUS_API_KEY")
# NVIDIA's own gateway serves the Nemotron family with an ``nvapi-`` key and
# publishes the same model ids as the Nebius catalogue.  Which one answers is
# decided by the key that is configured, never by the id alone.
NVIDIA_API_KEY = _env("NVIDIA_API_KEY")
GEMINI_PROXY_URL = "https://generativelanguage.googleapis.com/v1beta"
DEEPSEEK_PROXY_URL = "https://api.deepseek.com/v1"
QWEN_PROXY_URL = "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
# Nebius Token Factory serves the NVIDIA open models (Nemotron) behind an
# OpenAI-compatible API.  Overridable so a self-hosted Serverless Endpoint can
# be pointed at without touching code.
NEBIUS_PROXY_URL = _env("NEBIUS_PROXY_URL", "https://api.tokenfactory.nebius.com/v1")
# NVIDIA's catalog gateway: the endpoint used by ``integrate.api.nvidia.com``.
NVIDIA_PROXY_URL = _env("NVIDIA_PROXY_URL", "https://integrate.api.nvidia.com/v1")
# Upper bound for one chat request's provider calls, fallbacks included.  It
# stays below the backend task client's 120 s timeout so the proxy answers
# (with an error if need be) before the caller gives up on it.
LLM_UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("LLM_UPSTREAM_TIMEOUT_SECONDS", "110"))

# --- API Key Validation (deferred to after logger is defined) ---

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm-proxy")


# --- API Key Validation ---
def _validate_api_keys():
    """Ask each provider to authenticate, so a bad key fails loudly at startup."""
    return validate_api_keys(
        {
            "gemini": GEMINI_API_KEY,
            "deepseek": DEEPSEEK_API_KEY,
            "qwen": QWEN_API_KEY,
            "nebius": NEBIUS_API_KEY,
            "nvidia": NVIDIA_API_KEY,
        },
        {
            "gemini": GEMINI_PROXY_URL,
            "deepseek": DEEPSEEK_PROXY_URL,
            "qwen": QWEN_PROXY_URL,
            "nebius": NEBIUS_PROXY_URL,
            "nvidia": NVIDIA_PROXY_URL,
        },
    )


_validate_api_keys()


# --- Database ---
def _build_database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "factory")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "factory")
    # 2.1 defaults to psycopg3; this image ships psycopg2.
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
engine = create_engine(_build_database_url(), pool_pre_ping=True)

# --- Dynamic Model Catalogue ---

# Preference order for fallback resolution (most preferred first).
# Only used when the exact requested model is not in the live catalogue.
_PREFERENCE_TIERS = {
    "fast":     ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-flash-lite",
                 "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"],
    "powerful": ["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-pro-latest",
                 "gemini-2.5-pro"],
}

_available_models: set[str] = set()
_available_deepseek_models: set[str] = set()
_available_qwen_models: set[str] = set()
_available_nebius_models: set[str] = set()
_available_nvidia_models: set[str] = set()
_model_refresh_lock = threading.Lock()
_last_refresh: float = 0
_deepseek_last_refresh: float = 0
_qwen_last_refresh: float = 0
_nebius_last_refresh: float = 0
_nvidia_last_refresh: float = 0


def _refresh_gemini_models():
    global _available_models, _last_refresh
    _available_models, _last_refresh = _refresh("gemini", GEMINI_API_KEY, GEMINI_PROXY_URL,
                                                _available_models, _last_refresh)


def _refresh_deepseek_models():
    global _available_deepseek_models, _deepseek_last_refresh
    _available_deepseek_models, _deepseek_last_refresh = _refresh(
        "deepseek", DEEPSEEK_API_KEY, DEEPSEEK_PROXY_URL,
        _available_deepseek_models, _deepseek_last_refresh)


def _refresh_qwen_models():
    global _available_qwen_models, _qwen_last_refresh
    _available_qwen_models, _qwen_last_refresh = _refresh(
        "qwen", QWEN_API_KEY, QWEN_PROXY_URL, _available_qwen_models, _qwen_last_refresh)


def _refresh_nebius_models():
    global _available_nebius_models, _nebius_last_refresh
    _available_nebius_models, _nebius_last_refresh = _refresh(
        "nebius", NEBIUS_API_KEY, NEBIUS_PROXY_URL,
        _available_nebius_models, _nebius_last_refresh)


def _refresh_nvidia_models():
    global _available_nvidia_models, _nvidia_last_refresh
    _available_nvidia_models, _nvidia_last_refresh = _refresh(
        "nvidia", NVIDIA_API_KEY, NVIDIA_PROXY_URL,
        _available_nvidia_models, _nvidia_last_refresh)


def _refresh(provider, key, base_url, current, last_refresh):
    """Fetch one provider's catalogue. A failure keeps the previous one."""
    if not key:
        return current, last_refresh
    try:
        ids = fetch_model_ids(provider, key, base_url)
    except Exception as e:
        logger.warning(f"{provider} model refresh failed: {e}")
        return current, last_refresh
    logger.info(f"{provider} models refreshed: {sorted(ids)}")
    return ids, time.time()


# A model id names its provider by prefix.  The id must also be in that
# provider's fetched catalogue before a request is sent anywhere.
# Nebius ids carry a vendor segment ("nvidia/…", "meta-llama/…"), hence the
# vendor/ prefix rather than a bare model-name prefix.
# Order matters: the first provider whose key answers a matching id wins, so
# "nvidia/" is listed twice on purpose (NVIDIA's own gateway, then Nebius as
# the alternative host for the same open models).
_PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-", "gemma-"),
    "deepseek": ("deepseek-",),
    "qwen": ("qwen", "qwq-", "qvq-"),
    "nvidia": ("nvidia/",),
    "nebius": ("nvidia/", "meta-llama/", "mistralai/", "deepseek-ai/", "qwen/", "google/"),
}

# Where a request goes when its provider answers 429 or 5xx, in order.  Each
# candidate is used only if it is in that provider's catalogue.
_FALLBACK_CANDIDATES: list[tuple[str, list[str]]] = [
    ("deepseek", ["deepseek-flash"]),
    ("qwen", ["qwen3.6-flash"]),
    ("gemini", _PREFERENCE_TIERS["fast"]),
]


def providers_for_model(model_id: str) -> list[str]:
    """Every provider whose prefix *model_id* carries, most specific first."""
    lower = (model_id or "").strip().lower()
    return [p for p, prefixes in _PROVIDER_PREFIXES.items() if lower.startswith(prefixes)]


def provider_for_model(model_id: str) -> str | None:
    """The first provider that could serve *model_id*, or ``None``."""
    candidates = providers_for_model(model_id)
    return candidates[0] if candidates else None


def _provider_key(provider: str) -> str:
    return {"gemini": GEMINI_API_KEY, "deepseek": DEEPSEEK_API_KEY, "qwen": QWEN_API_KEY,
            "nebius": NEBIUS_API_KEY, "nvidia": NVIDIA_API_KEY}.get(provider, "")


def _provider_catalogue(provider: str) -> set[str]:
    """The provider's fetched model ids that route to it, refreshing once if empty."""
    sources = {
        "gemini": (_refresh_gemini_models, lambda: _available_models),
        "deepseek": (_refresh_deepseek_models, lambda: _available_deepseek_models),
        "qwen": (_refresh_qwen_models, lambda: _available_qwen_models),
        "nebius": (_refresh_nebius_models, lambda: _available_nebius_models),
        "nvidia": (_refresh_nvidia_models, lambda: _available_nvidia_models),
    }
    if provider not in sources:
        return set()
    refresh, current = sources[provider]
    if not current() and _provider_key(provider):
        refresh()
    with _model_refresh_lock:
        ids = set(current())
    return {mid for mid in ids if provider in providers_for_model(mid)}


def available_model_ids() -> list[str]:
    """Every model id the chat endpoint routes, as ``/v1/models`` lists them."""
    ids: set[str] = set()
    for provider in _PROVIDER_PREFIXES:
        catalogue = _provider_catalogue(provider)
        if provider == "gemini":
            catalogue -= _GEMINI_DEPRECATED
        ids |= catalogue
    return sorted(ids)


def resolve_model(requested: str) -> tuple[str, str] | None:
    """
    Return ``(provider, model_id)`` for *requested*, or ``None`` when no
    provider serves it.  Providers that share a vendor prefix (``nvidia/`` on
    NVIDIA's gateway and on Nebius) are tried in order and only those with a
    configured key are considered, so one id works whichever key exists.  A
    deprecated Gemini id is aliased to its replacement when the replacement is
    in the catalogue.  Nothing else is substituted.
    """
    candidates = providers_for_model(requested)
    if not candidates:
        return None
    for provider in candidates:
        if not _provider_key(provider):
            continue
        catalogue = _provider_catalogue(provider)
        if provider == "gemini":
            alias = _GEMINI_ALIASES.get(requested)
            if alias and alias in catalogue:
                return provider, alias
        if requested in catalogue:
            return provider, requested
    return None


def _fallback_targets(failed_provider: str) -> list[tuple[str, str]]:
    """Catalogue models to try, one per other provider, after a 429/5xx."""
    targets = []
    for provider, candidates in _FALLBACK_CANDIDATES:
        if provider == failed_provider:
            continue
        catalogue = _provider_catalogue(provider)
        for candidate in candidates:
            if candidate in catalogue:
                targets.append((provider, candidate))
                break
    return targets


# Refresh models once at startup; background thread refreshes every hour.
_refresh_gemini_models()
_refresh_deepseek_models()
_refresh_qwen_models()
_refresh_nebius_models()
_refresh_nvidia_models()
threading.Thread(target=lambda: (time.sleep(3600), _refresh_gemini_models()), daemon=True).start()
threading.Thread(target=lambda: (time.sleep(3600), _refresh_deepseek_models()), daemon=True).start()
threading.Thread(target=lambda: (time.sleep(3600), _refresh_qwen_models()), daemon=True).start()
threading.Thread(target=lambda: (time.sleep(3600), _refresh_nebius_models()), daemon=True).start()
threading.Thread(target=lambda: (time.sleep(3600), _refresh_nvidia_models()), daemon=True).start()

# --- Governance Middleware ---
@app.before_request
def enforce_business_unit_quota():
    if request.path == "/health": return
    bu_id = request.headers.get("X-Business-Unit-ID")
    if not bu_id: return
    try:
        with engine.connect() as conn:
            query = text("SELECT token_quota_limit, token_quota_used FROM business_units WHERE id = :id")
            res = conn.execute(query, {"id": bu_id}).fetchone()
            if not res: return jsonify({"error": "Business Unit not found"}), 404
            limit, used = res
            if limit > 0 and used >= limit:
                return jsonify({"error": "Quota exceeded", "used": used, "limit": limit}), 429
    except Exception as e:
        logger.error(f"Quota check failed: {e}")


@app.after_request
def add_quota_warning_header(response):
    """Add X-Quota-Warning header when a business unit has consumed ≥ 80 % of its limit."""
    bu_id = request.headers.get("X-Business-Unit-ID")
    if not bu_id:
        return response
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT token_quota_limit, token_quota_used FROM business_units WHERE id = :id"),
                {"id": bu_id},
            ).fetchone()
            if res:
                limit, used = res
                if limit > 0 and used >= limit * 0.8:
                    response.headers["X-Quota-Warning"] = "true"
                    response.headers["X-Quota-Used"] = str(used)
                    response.headers["X-Quota-Limit"] = str(limit)
    except Exception as e:
        logger.error(f"Quota warning check failed: {e}")
    return response

# --- Usage Tracking ---
def track_usage_in_db(bu_id, tokens):
    """Track token usage in the database for a business unit."""
    if not bu_id:
        return
    try:
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE business_units SET token_quota_used = token_quota_used + :tokens WHERE id = :id"),
                {"tokens": tokens, "id": bu_id},
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to track usage in DB: {e}")


# --- API Endpoints ---

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "database": "connected", "models": sorted(_available_models)})


@app.route("/v1/models")
def list_models():
    """
    Return a structured catalogue of all available models with tier classification.

    Response schema:
      {
        "models": [
          {
            "id":          "gemini-2.5-pro",
            "provider":    "gemini" | "deepseek" | "qwen" | "nebius",
            "tier":        "strategic" | "balanced" | "code" | "fast" | "preview",
            "description": "..."
          },
          ...
        ],
        "orchestrator": "gemini-2.5-flash",   // recommended model for meta-tasks
        "refreshed_at": 1712345678.0
      }
    """
    # Only ids the chat endpoint routes are listed.
    models = []
    for model_id in sorted(_provider_catalogue("gemini") - _GEMINI_DEPRECATED):
        tier, desc = _classify_model(model_id)
        models.append({"id": model_id, "provider": "gemini", "tier": tier, "description": desc})

    # DeepSeek models are available only when the API key is configured.
    if DEEPSEEK_API_KEY:
        ds_ids = sorted(_provider_catalogue("deepseek"))
        for mid in ds_ids:
            tier = "fast" if "flash" in mid else "balanced"
            models.append({"id": mid, "provider": "deepseek", "tier": tier,
                           "description": f"DeepSeek {mid}"})

    # Qwen models are available only when the API key is configured.
    if QWEN_API_KEY:
        q_ids = sorted(_provider_catalogue("qwen"))
        for mid in q_ids:
            lower = mid.lower()
            if "max" in lower:
                tier = "strategic"
            elif "flash" in lower:
                tier = "balanced"
            else:
                tier = "balanced"
            models.append({"id": mid, "provider": "qwen", "tier": tier,
                           "description": f"Qwen {mid}"})

    # NVIDIA's own gateway, then Nebius, serve the open models (Nemotron); an
    # id both serve is listed once, under the provider that would answer it.
    listed: set[str] = set()
    for provider, key, label in (("nvidia", NVIDIA_API_KEY, "NVIDIA"), ("nebius", NEBIUS_API_KEY, "NVIDIA/Nebius")):
        if not key:
            continue
        for mid in sorted(_provider_catalogue(provider) - listed):
            models.append({"id": mid, "provider": provider, "tier": open_model_tier(mid),
                           "description": f"{label} {mid}"})
            listed.add(mid)

    # Pick the best non-preview balanced/fast model for orchestration tasks
    # (team suggestion, routing decisions) — prefer stability over power.
    orchestrator = _pick_orchestrator(models)

    return jsonify({"models": models, "orchestrator": orchestrator, "refreshed_at": _last_refresh})


def _pick_orchestrator(models: list[dict]) -> str:
    """
    Choose the best model for short orchestration/meta tasks (fast, stable, not preview).
    Preference: balanced > fast > strategic, never preview.
    """
    preferred_ids = [
        "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-flash-lite",
        "gemini-2.5-flash", "gemini-2.5-pro",
    ]
    available_ids = {m["id"] for m in models if m["tier"] != "preview"}
    for candidate in preferred_ids:
        if candidate in available_ids:
            return candidate
    # Fall back to any non-preview balanced model
    for m in models:
        if m["tier"] in ("balanced", "fast") and m["tier"] != "preview":
            return m["id"]
    return models[0]["id"] if models else "gemini-flash-latest"


UpstreamError = upstream.UpstreamError
_upstream_message = upstream.upstream_message
_post_upstream = upstream.post_upstream


_OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": DEEPSEEK_PROXY_URL,
    "qwen": QWEN_PROXY_URL,
    "nebius": NEBIUS_PROXY_URL,
    "nvidia": NVIDIA_PROXY_URL,
}


def _call_openai_compatible(provider: str, model: str, data: dict, timeout: float) -> tuple[dict, int]:
    base_url = _OPENAI_COMPATIBLE_BASE_URLS[provider]
    status, result = _post_upstream(
        provider,
        model,
        f"{base_url}/chat/completions",
        {"Authorization": f"Bearer {_provider_key(provider)}"},
        {**data, "model": model},
        timeout,
    )
    if not result.get("choices"):
        raise UpstreamError(provider, model, status, "response contained no choices", retriable=False)
    return with_usage(result, openai_reported_count(result), data.get("messages", []), openai_text(result))


def _call_gemini(model: str, data: dict, timeout: float) -> tuple[dict, int]:
    messages = data.get("messages", [])
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    payload = {"contents": contents, "generationConfig": {"temperature": data.get("temperature", 0.7)}}
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    status, res = _post_upstream(
        "gemini",
        model,
        f"{GEMINI_PROXY_URL}/models/{model}:generateContent",
        {"x-goog-api-key": GEMINI_API_KEY},
        payload,
        timeout,
    )
    try:
        text_out = res["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        reason = (res.get("promptFeedback") or {}).get("blockReason") or "no candidates"
        raise UpstreamError("gemini", model, status, f"response had no text ({reason})", retriable=False)
    result = {"choices": [{"message": {"role": "assistant", "content": text_out}}], "model": model}
    reported = reported_count((res.get("usageMetadata") or {}).get("totalTokenCount"))
    return with_usage(result, reported, messages, text_out)


def _call_provider(provider: str, model: str, data: dict, timeout: float) -> tuple[dict, int]:
    if provider == "gemini":
        return _call_gemini(model, data, timeout)
    return _call_openai_compatible(provider, model, data, timeout)


def _complete_with_fallback(provider: str, model: str, data: dict) -> tuple[dict, int, str, str, dict | None]:
    """
    Call the resolved model; on 429/5xx try one catalogue model per other
    provider within the same time budget.  Returns
    ``(result, tokens, served_provider, served_model, fallback_from)`` or
    raises the primary ``UpstreamError`` with every attempt attached.
    """
    deadline = time.monotonic() + LLM_UPSTREAM_TIMEOUT_SECONDS
    try:
        result, tokens = _call_provider(provider, model, data, LLM_UPSTREAM_TIMEOUT_SECONDS)
        return result, tokens, provider, model, None
    except UpstreamError as primary:
        if not primary.retriable:
            raise
        logger.warning("%s; trying fallback models from the catalogue", primary)
        primary.attempts = [primary.as_dict()]
        for fb_provider, fb_model in _fallback_targets(provider):
            remaining = deadline - time.monotonic()
            if remaining < 5:
                break
            try:
                result, tokens = _call_provider(fb_provider, fb_model, data, remaining)
            except UpstreamError as exc:
                logger.warning("Fallback failed: %s", exc)
                primary.attempts.append(exc.as_dict())
                if not exc.retriable:
                    break
                continue
            return result, tokens, fb_provider, fb_model, primary.as_dict()
        raise primary


def _flatten_extra_body(data: dict) -> dict:
    """The OpenAI SDK merges ``extra_body`` into the request; some clients nest it."""
    extra = data.pop("extra_body", None)
    if isinstance(extra, dict):
        return {**extra, **data}
    return data


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    # Flatten first, so a ``stream`` nested in ``extra_body`` is refused too.
    data = _flatten_extra_body(request.get_json(silent=True) or {})
    requested = str(data.get("model") or "").strip()
    bu_id = request.headers.get("X-Business-Unit-ID")

    if data.get("stream"):
        # The proxy relays one finished answer; an SSE client would hang on a
        # body it cannot parse.  Saying so beats a 500 from ``resp.json()``.
        return jsonify({
            "error": "stream_unsupported",
            "model": requested,
            "message": "stream=true is not supported here; send stream=false "
                       "(or call the provider endpoint directly to stream)",
        }), 400

    if not requested:
        return jsonify({
            "error": "model_required",
            "model": "",
            "message": "request named no model",
            "available": available_model_ids(),
        }), 400

    resolved = resolve_model(requested)
    if resolved is None:
        available = available_model_ids()
        return jsonify({
            "error": "unknown_model",
            "model": requested,
            "provider": provider_for_model(requested),
            "message": f"unknown model '{requested}'; available: {', '.join(available) or 'none'}",
            "available": available,
        }), 400

    provider, model = resolved
    try:
        result, tokens, served_provider, served_model, fallback_from = _complete_with_fallback(provider, model, data)
    except UpstreamError as exc:
        body = {"error": "upstream_error", **exc.as_dict(), "requested_model": requested}
        if len(exc.attempts) > 1:
            body["attempts"] = exc.attempts
        return jsonify(body), 429 if exc.status == 429 else 502
    except Exception as exc:  # noqa: BLE001 - surface proxy bugs as JSON, not an HTML page
        logger.exception("chat_completions failed")
        return jsonify({"error": "proxy_error", "message": str(exc)}), 500

    result["served_model"] = served_model
    result["provider"] = served_provider
    result["requested_model"] = requested
    if fallback_from is not None:
        result["fallback_from"] = fallback_from
    track_usage_in_db(bu_id, tokens)
    return jsonify(result)


@app.route("/v1/embeddings", methods=["POST"])
def embeddings():
    data = request.json or {}
    input_text = data.get("input", "")
    if isinstance(input_text, list):
        input_text = "\n".join(str(item) for item in input_text)
    input_text = str(input_text)

    bu_id = request.headers.get("X-Business-Unit-ID")

    if not input_text.strip():
        return jsonify({"error": "input is required"}), 400

    try:
        if GEMINI_API_KEY:
            payload = {
                "model": "models/text-embedding-004",
                "content": {
                    "parts": [{"text": input_text}],
                },
                "taskType": data.get("taskType", "RETRIEVAL_DOCUMENT"),
            }
            resp = requests.post(
                f"{GEMINI_PROXY_URL}/models/text-embedding-004:embedContent",
                headers={"x-goog-api-key": GEMINI_API_KEY},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
            values = body.get("embedding", {}).get("values") or []
            if values:
                estimate = max(1, len(input_text) // 4)
                track_usage_in_db(bu_id, estimate)
                return jsonify(
                    {
                        "data": [{"embedding": values, "index": 0}],
                        "model": "text-embedding-004",
                        **estimated_usage(estimate),
                    }
                )

        fallback = _fallback_embedding(input_text)
        return jsonify(
            {
                "data": [{"embedding": fallback, "index": 0}],
                "model": "local-fallback-embedding",
            }
        )
    except Exception as e:
        logger.warning("Embedding provider failed, using local fallback: %s", e)
        fallback = _fallback_embedding(input_text)
        return jsonify(
            {
                "data": [{"embedding": fallback, "index": 0}],
                "model": "local-fallback-embedding",
            }
        )

if __name__ == "__main__":
    # 0.0.0.0 inside Docker (the port is only published on the host loopback);
    # a desktop launcher passes 127.0.0.1 because this process holds the keys.
    app.run(
        host=os.getenv("PROXY_HOST", "0.0.0.0"),
        port=int(os.getenv("PROXY_PORT", 5100)),
    )
