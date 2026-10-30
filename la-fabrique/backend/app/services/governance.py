"""Governance gates for autonomous artifact materialization.

The factory must be able to evolve itself without blindly overwriting its own
runtime. This module provides a single decision surface that classifies
proposed artifact paths against a configured list of protected paths and,
optionally, redirects writes into a sandbox so that risky changes can be
reviewed before they affect production code.

What this protects against
--------------------------
- Self-improvement sprints proposing edits to the agent graph, workers, NATS
  client, LLM proxy, or model factory.
- Foundation/execution sprints trying to overwrite critical operational code
  through a generated artifact.

What this does NOT do (yet)
---------------------------
- Run a full container sandbox: that is the next iteration. The structure
  is intentionally factored so the same gate can later short-circuit into a
  worktree, a CI dry-run, or a human approval queue without touching every
  call site.

Behavior
--------
``classify_artifact`` returns a :class:`GateDecision`:
- ``status="allow"``        — write straight to the workspace.
- ``status="sandbox"``      — write under ``SELF_IMPROVEMENT_SANDBOX_ROOT``
  instead of the original path. (Only when sandboxing is configured.)
- ``status="block"``        — refuse the write. The worker reports it via
  GlassRoom and marks the task blocked for manual triage.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from config import settings
from logging_config import logger


@dataclass(frozen=True)
class GateDecision:
    status: str  # "allow" | "sandbox" | "block"
    path: str  # final path to write to (may be redirected)
    original_path: str
    reason: str
    matched_pattern: str | None = None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize(path: str) -> str:
    return (path or "").strip().lstrip("./").replace("\\", "/")


def _matches_protected(path: str, patterns: Sequence[str]) -> str | None:
    """Return the first pattern that matches *path*.

    Patterns can be:
    - exact paths (``backend/app/main.py``),
    - directory prefixes ending with ``/`` (``backend/agents/``),
    - simple ``*`` suffix wildcards (``backend/llm/*``).
    """
    norm = _normalize(path)
    for pattern in patterns:
        p = _normalize(pattern)
        if not p:
            continue
        if p.endswith("/*"):
            prefix = p[:-1]
            if norm.startswith(prefix):
                return pattern
            continue
        if p.endswith("/"):
            if norm.startswith(p):
                return pattern
            continue
        if norm == p:
            return pattern
        # Allow directory match when pattern has no extension.
        if "." not in p and norm.startswith(p + "/"):
            return pattern
    return None


def get_protected_patterns() -> list[str]:
    return _split_csv(getattr(settings, "SELF_IMPROVEMENT_PROTECTED_PATHS", ""))


def get_sandbox_root(override: str | None = None) -> str | None:
    sandbox = (
        override
        if override is not None
        else (getattr(settings, "SELF_IMPROVEMENT_SANDBOX_ROOT", "") or "")
    )
    return sandbox.strip() or None


def classify_artifact(
    path: str,
    *,
    is_self_improvement: bool,
    sandbox_root: str | None = None,
    extra_protected: Iterable[str] | None = None,
) -> GateDecision:
    """Decide what to do with a proposed artifact write.

    Args:
        path: Repository-relative path the agent wants to write.
        is_self_improvement: True when the sprint targets the factory itself.
            Self-improvement sprints have stricter rules — protected paths are
            blocked unless an approval gate is present (sandbox redirect or
            explicit override).
        extra_protected: Additional patterns to apply on top of settings.
    """
    norm = _normalize(path)
    patterns = list(get_protected_patterns())
    if extra_protected:
        patterns.extend(extra_protected)

    matched = _matches_protected(norm, patterns)
    if not matched:
        return GateDecision(
            status="allow",
            path=norm,
            original_path=norm,
            reason="no_protected_match",
        )

    sandbox = get_sandbox_root(sandbox_root)
    if sandbox:
        sandboxed = f"{sandbox.rstrip('/')}/{norm}"
        logger.info(
            "governance: redirecting protected path %s → %s (matched %s)",
            norm,
            sandboxed,
            matched,
        )
        return GateDecision(
            status="sandbox",
            path=sandboxed,
            original_path=norm,
            reason="protected_path_sandboxed",
            matched_pattern=matched,
        )

    if is_self_improvement and getattr(
        settings, "SELF_IMPROVEMENT_REQUIRE_APPROVAL", True
    ):
        logger.warning(
            "governance: BLOCK self-improvement write to protected path %s (matched %s)",
            norm,
            matched,
        )
        return GateDecision(
            status="block",
            path=norm,
            original_path=norm,
            reason="protected_path_requires_approval",
            matched_pattern=matched,
        )

    # Non-self-improvement sprint touching a protected path is suspicious; we
    # block by default so generated content from a third-party project sprint
    # cannot accidentally overwrite the factory runtime.
    logger.warning(
        "governance: BLOCK third-party write to protected path %s (matched %s)",
        norm,
        matched,
    )
    return GateDecision(
        status="block",
        path=norm,
        original_path=norm,
        reason="protected_path_external_blocked",
        matched_pattern=matched,
    )


def classify_artifacts(
    artifacts: Sequence[dict],
    *,
    is_self_improvement: bool,
    sandbox_root: str | None = None,
) -> list[tuple[GateDecision, dict]]:
    """Classify every artifact in a workspace.generate batch.

    Returns a list of ``(decision, artifact)`` tuples in the original order.
    The artifact dict is returned untouched; callers are responsible for
    rewriting ``path`` based on ``decision.path`` and dropping blocked entries.
    """
    out: list[tuple[GateDecision, dict]] = []
    for art in artifacts:
        decision = classify_artifact(
            str(art.get("path", "")),
            is_self_improvement=is_self_improvement,
            sandbox_root=sandbox_root,
        )
        out.append((decision, art))
    return out
