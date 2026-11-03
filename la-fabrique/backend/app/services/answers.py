"""What the worker makes of a model's answer, before anything is recorded.

The proxy answers in the OpenAI shape. These readers say what the answer
holds (``llm_content``), why it is unusable (``llm_failure``), how the model
stopped (``llm_finish_reason``), what the gate says when the checks fail on
an answer the model could not finish (``gate_reason``), and what the review
prompt adds after a formless verdict (``review_format_reminder``). The caps
for the fixed-form answers live here too. None of this is evidence: a cut
deliverable is sent back, never recorded as written.
"""

from __future__ import annotations

from typing import Any

# Output budgets for the short answers: a review is two or three sentences, a
# brief a few paragraphs. The Developer's deliverable has none, since every
# file goes in full; a cut-off one is named by ``gate_reason`` instead.
REVIEW_MAX_TOKENS = 600
BRIEF_MAX_TOKENS = 1024

# What the gate says when the text checks fail on an answer the model could
# not finish: asking for "the complete result again" would cut it again.
CUT_OFF_REASON = (
    "Output cut off at the model's length limit, so the deliverable is "
    "incomplete; deliver fewer or smaller files, or split the task"
)


def llm_content(result: dict[str, Any]) -> str:
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content") or ""
    return (content if isinstance(content, str) else str(content)).strip()


def llm_finish_reason(result: dict[str, Any]) -> str | None:
    """Why the model stopped, as the proxy reports it (``length`` when cut at the limit)."""
    choices = result.get("choices") or [{}]
    reason = (choices[0] or {}).get("finish_reason")
    return str(reason) if reason else None


def llm_failure(result: dict[str, Any], model: str) -> str | None:
    """
    Describe why *result* carries no usable answer, or return ``None``.

    The text reads ``LLM call failed: <provider> <status> <message>``.  The
    proxy reports provider errors as ``{"provider", "status", "message"}``;
    errors of the proxy itself (unknown model, quota) name ``llm-proxy`` and
    the HTTP status.  A 2xx answer with empty content is a failure too, so it
    never reaches the word-count gate as an empty deliverable.
    """
    if result.get("error"):
        detail = result.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        provider = detail.get("provider") or "llm-proxy"
        status = detail.get("status") or result.get("status_code") or "unreachable"
        message = detail.get("message") or detail.get("error") or result["error"]
        return f"LLM call failed: {provider} {status} {message}"
    if not llm_content(result):
        provider = result.get("provider") or "llm-proxy"
        served = result.get("served_model") or model
        return f"LLM call failed: {provider} 200 empty response from {served}"
    return None


def gate_reason(validation_reason: str, finish_reason: str | None) -> str:
    return CUT_OFF_REASON if finish_reason == "length" else validation_reason


def review_format_reminder(earlier_failures: int) -> str:
    """What the review prompt adds once an answer came back without a verdict.

    Sending the same prompt again after a formless answer mostly buys the same
    answer; naming the miss is what changes it.
    """
    if earlier_failures <= 0:
        return ""
    return (
        f"\n\nYour previous {'answer' if earlier_failures == 1 else 'answers'} to this "
        "review could not be used because the first word was not 'APPROVED:' or "
        "'NEEDS WORK:'. Begin with one of those two, then the review."
    )
