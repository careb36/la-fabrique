"""
How a call's token count is known.

Only ``reported`` is the provider's own figure, and only it goes in the
response's ``usage``. When the provider gives no count, an estimate
(characters / 4) is charged to the business unit's quota, so a budget cannot
leak, but it travels apart as ``usage_estimate`` with ``usage_status:
estimated`` and is never presented as usage.
"""

import math

USAGE_REPORTED = "reported"
USAGE_ESTIMATED = "estimated"


def reported_count(value) -> int | None:
    """A provider's count, or ``None`` when it is missing or not a count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def openai_reported_count(result: dict) -> int | None:
    """The total an OpenAI-compatible answer reports, or its prompt + completion split."""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    total = reported_count(usage.get("total_tokens"))
    if total is not None:
        return total
    prompt = reported_count(usage.get("prompt_tokens"))
    completion = reported_count(usage.get("completion_tokens"))
    if prompt is not None and completion is not None:
        return prompt + completion
    return None


def openai_text(result: dict) -> str:
    try:
        return result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def estimated_usage(estimate: int) -> dict:
    """The fields a response carries when its count is only an estimate."""
    return {"usage_status": USAGE_ESTIMATED, "usage_estimate": estimate}


def estimate_tokens(messages, text_out: str) -> int:
    return max(1, (len(str(messages)) + len(text_out or "")) // 4)


def with_usage(result: dict, reported: int | None, messages, text_out: str) -> tuple[dict, int]:
    """Mark how the call's tokens are known; return the count to charge."""
    if reported is not None:
        result["usage"] = {**(result.get("usage") or {}), "total_tokens": reported}
        result["usage_status"] = USAGE_REPORTED
        return result, reported
    estimate = estimate_tokens(messages, text_out)
    result.pop("usage", None)
    result.update(estimated_usage(estimate))
    return result, estimate


def fallback_embedding(text: str, dims: int = 1536) -> list[float]:
    """Deterministic local embedding fallback used only when provider embedding fails."""
    vector = [0.0] * dims
    for index, byte in enumerate(text.encode("utf-8")):
        slot = (index * 131 + byte) % dims
        vector[slot] += (byte % 17) + 1
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
