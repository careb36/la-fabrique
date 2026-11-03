"""Gemini's request and answer, translated to and from the OpenAI shape.

The proxy speaks OpenAI's chat format to every provider; Gemini has its own.
This module builds its ``generateContent`` body (system instruction, contents,
``generationConfig`` with the caller's ``max_tokens`` as ``maxOutputTokens``)
and reads its answer back into ``choices`` with the same ``finish_reason``
the OpenAI-compatible providers report, so a caller can tell an answer cut
at the limit (``length``) from a complete one.
"""

from collections.abc import Callable

from upstream import UpstreamError
from usage import reported_count, with_usage

# Gemini's finishReason, as the OpenAI-compatible providers spell it.
FINISH_REASONS = {"MAX_TOKENS": "length", "STOP": "stop"}


def call_gemini(
    model: str,
    data: dict,
    timeout: float,
    *,
    post: Callable[..., tuple[int, dict]],
    base_url: str,
    api_key: str,
) -> tuple[dict, int]:
    """One ``generateContent`` call through *post* (the proxy's upstream POST)."""
    messages = data.get("messages", [])
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    generation: dict = {"temperature": data.get("temperature", 0.7)}
    if data.get("max_tokens"):
        generation["maxOutputTokens"] = int(data["max_tokens"])
    payload: dict = {"contents": contents, "generationConfig": generation}
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    status, res = post(
        "gemini", model, f"{base_url}/models/{model}:generateContent", {"x-goog-api-key": api_key}, payload, timeout
    )
    try:
        candidate = res["candidates"][0]
        text_out = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        reason = (res.get("promptFeedback") or {}).get("blockReason") or "no candidates"
        raise UpstreamError("gemini", model, status, f"response had no text ({reason})", retriable=False)
    finish = FINISH_REASONS.get(str(candidate.get("finishReason") or "").upper(), "other")
    result = {
        "choices": [{"message": {"role": "assistant", "content": text_out}, "finish_reason": finish}],
        "model": model,
    }
    reported = reported_count((res.get("usageMetadata") or {}).get("totalTokenCount"))
    return with_usage(result, reported, messages, text_out)
