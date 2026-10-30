"""
Workspace snapshot — read-only views of the target repo for agents and QA.

Two responsibilities:

1. ``build_task_snapshot`` — given a task (title + description), return a short
   text block listing the most relevant files in the workspace plus a short
   excerpt of each. Injected into the Developer/Architect/QA prompt so the
   agent does not hallucinate paths or APIs that do not exist.

2. ``read_artifact_evidence`` — given a list of file paths the deliverable
   *claims* to have produced, read each from the workspace and report what is
   actually there. Used by QA to detect "approved deliverable, empty file"
   false positives.

Both helpers are blocking I/O and meant to be called via ``asyncio.to_thread``.
The repo tree is cached per ``workspace_root`` with a short TTL so concurrent
tasks in the same sprint do not re-walk the whole tree.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterable

from logging_config import setup_logger

logger = setup_logger("fabrique-workspace-snapshot")


# ---------------------------------------------------------------------------
# Tunables — overridable via env without redeploy.
# ---------------------------------------------------------------------------

WORKSPACE_SNAPSHOT_ENABLED = os.getenv(
    "WORKSPACE_SNAPSHOT_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}
SNAPSHOT_CACHE_TTL_SECONDS = max(
    10, int(os.getenv("WORKSPACE_SNAPSHOT_CACHE_TTL", "60"))
)
SNAPSHOT_MAX_FILES = max(20, int(os.getenv("WORKSPACE_SNAPSHOT_MAX_FILES", "4000")))
SNAPSHOT_TOP_RELEVANT = max(3, int(os.getenv("WORKSPACE_SNAPSHOT_TOP_RELEVANT", "5")))
SNAPSHOT_LINES_PER_FILE = max(
    20, int(os.getenv("WORKSPACE_SNAPSHOT_LINES_PER_FILE", "60"))
)
EVIDENCE_LINES_PER_FILE = max(
    20, int(os.getenv("WORKSPACE_EVIDENCE_LINES_PER_FILE", "80"))
)
EVIDENCE_MAX_FILE_BYTES = max(
    2048, int(os.getenv("WORKSPACE_EVIDENCE_MAX_FILE_BYTES", "65536"))
)


_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".tox",
        "dist",
        "build",
        "out",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        "target",
        "vendor",
        ".idea",
        ".vscode",
        ".fabrique",  # our own runtime artifacts
    }
)

_INTERESTING_EXTS = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".cs",
        ".swift",
        ".sql",
        ".graphql",
        ".proto",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".md",
        ".rst",
        ".sh",
        ".bash",
        ".tf",
        ".hcl",
        ".css",
        ".scss",
        ".html",
    }
)

_SIGNAL_BASENAMES = frozenset(
    {
        "README.md",
        "README.rst",
        "README",
        "CLAUDE.md",
        "ARCHITECTURE.md",
        "CONTRIBUTING.md",
        "package.json",
        "tsconfig.json",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "go.mod",
        "go.sum",
        "Cargo.toml",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Makefile",
    }
)

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "this",
        "that",
        "is",
        "are",
        "be",
        "as",
        "it",
        "its",
        "task",
        "build",
        "create",
        "add",
        "implement",
        "update",
        "fix",
        "make",
        "use",
        "via",
        "into",
        "new",
        "all",
        "any",
        "must",
        "should",
        "can",
        "will",
        "have",
        "has",
        "ensure",
        "support",
        "handle",
        "plus",
        "del",
        "la",
        "el",
        "los",
        "las",
        "y",
        "o",
        "para",
        "que",
        "con",
        "por",
        "una",
        "un",
        "se",
        "lo",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_tree_cache: dict[str, tuple[float, list[str]]] = {}


def _list_workspace_files(workspace_root: str) -> list[str]:
    """Walk the workspace and return relative file paths, with caching."""
    now = time.monotonic()
    with _cache_lock:
        cached = _tree_cache.get(workspace_root)
        if cached and (now - cached[0]) < SNAPSHOT_CACHE_TTL_SECONDS:
            return cached[1]

    files: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(workspace_root, followlinks=False):
            # Prune ignored dirs in-place so os.walk does not descend.
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _IGNORED_DIRS and not d.startswith(".terraform")
            ]
            rel_dir = os.path.relpath(dirpath, workspace_root)
            for name in filenames:
                if name.startswith(".") and name not in _SIGNAL_BASENAMES:
                    # Hidden files rarely useful for context (.DS_Store, .pyc).
                    continue
                rel = name if rel_dir == "." else os.path.join(rel_dir, name)
                rel = rel.replace("\\", "/")
                files.append(rel)
                if len(files) >= SNAPSHOT_MAX_FILES:
                    break
            if len(files) >= SNAPSHOT_MAX_FILES:
                break
    except (OSError, PermissionError) as exc:
        logger.warning("workspace walk failed for %s: %s", workspace_root, exc)
        files = []

    with _cache_lock:
        _tree_cache[workspace_root] = (now, files)
    return files


def invalidate_cache(workspace_root: str | None = None) -> None:
    """Drop cached tree for a workspace (or all). Useful for tests."""
    with _cache_lock:
        if workspace_root is None:
            _tree_cache.clear()
        else:
            _tree_cache.pop(workspace_root, None)


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}
    # Split CamelCase and snake_case derivatives so the title "AddUserAuth"
    # matches files named "user_auth.py".
    extra: set[str] = set()
    for tok in tokens:
        for piece in re.split(r"[_\-]+", tok):
            if len(piece) >= 3:
                extra.add(piece.lower())
        # Camel-case split: lowercase boundaries.
        for piece in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", tok):
            if len(piece) >= 3:
                extra.add(piece.lower())
    tokens |= extra
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 3}


def _score_path(path: str, task_tokens: set[str]) -> int:
    """Heuristic: heavier weight on basename, lighter on directory components."""
    if not task_tokens:
        return 0
    basename = os.path.basename(path).lower()
    stem, ext = os.path.splitext(basename)
    base_tokens = _tokenize(stem)
    parent_tokens = _tokenize(path[: -len(basename)])

    base_match = len(base_tokens & task_tokens) * 4
    dir_match = len(parent_tokens & task_tokens)

    score = base_match + dir_match
    if score == 0:
        return 0

    # Lift code over docs/configs when relevance ties; QA-style tasks already
    # bias toward docs via stem matching ("readme", "architecture").
    if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}:
        score += 1
    return score


def _read_excerpt(
    abs_path: str, max_lines: int, max_bytes: int = EVIDENCE_MAX_FILE_BYTES
) -> tuple[str | None, int]:
    """Read first ``max_lines`` of a file; return (excerpt, total_byte_size).

    Returns (None, 0) if the file is unreadable. Empty file yields ("", 0)
    so the caller can distinguish "missing" from "present but empty".
    """
    try:
        size = os.path.getsize(abs_path)
    except OSError:
        return None, 0

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            chunk = fh.read(max_bytes)
    except (OSError, ValueError) as exc:
        logger.debug("evidence read failed %s: %s", abs_path, exc)
        return None, size

    lines = chunk.splitlines()
    if len(lines) > max_lines:
        excerpt = (
            "\n".join(lines[:max_lines]) + f"\n… [+{len(lines) - max_lines} more lines]"
        )
    else:
        excerpt = "\n".join(lines)
    if size > max_bytes:
        excerpt += f"\n… [file truncated; total {size} bytes]"
    return excerpt, size


# ---------------------------------------------------------------------------
# Public API — snapshot for execution
# ---------------------------------------------------------------------------


def build_task_snapshot(
    task_title: str,
    task_description: str,
    workspace_root: str | None,
    *,
    max_chars: int = 4500,
) -> str:
    """Return a short repo snapshot relevant to the task, or "" if disabled/empty."""
    if not WORKSPACE_SNAPSHOT_ENABLED or not workspace_root:
        return ""
    if not os.path.isdir(workspace_root):
        return ""

    task_tokens = _tokenize(f"{task_title or ''} {task_description or ''}")
    files = _list_workspace_files(workspace_root)
    if not files:
        return ""

    # Always include high-signal top-level files even if they did not match.
    pinned: list[str] = [
        f for f in files if "/" not in f and os.path.basename(f) in _SIGNAL_BASENAMES
    ]

    candidates = [
        f
        for f in files
        if os.path.splitext(f)[1].lower() in _INTERESTING_EXTS
        or os.path.basename(f) in _SIGNAL_BASENAMES
    ]
    scored = sorted(
        ((s, p) for p in candidates if (s := _score_path(p, task_tokens)) > 0),
        key=lambda x: (-x[0], len(x[1])),
    )
    top_relevant = [p for _, p in scored[:SNAPSHOT_TOP_RELEVANT]]

    parts: list[str] = []
    parts.append(f"Workspace root: {workspace_root}")
    parts.append(f"Total files indexed: {len(files)}.")

    def _emit_excerpt(rel: str, max_lines: int) -> None:
        abs_path = os.path.join(workspace_root, rel)
        excerpt, size = _read_excerpt(abs_path, max_lines=max_lines)
        if excerpt is None:
            parts.append(f"\n— `{rel}` ({size} bytes — could not read)")
            return
        if not excerpt.strip():
            parts.append(f"\n— `{rel}` (empty)")
            return
        parts.append(f"\n— `{rel}` ({size} bytes)")
        parts.append("```")
        parts.append(excerpt)
        parts.append("```")

    # Task-relevant files first — most directly useful for grounding the agent.
    if top_relevant:
        parts.append("")
        parts.append("### Files relevant to this task")
        for rel in top_relevant:
            _emit_excerpt(rel, SNAPSHOT_LINES_PER_FILE)

    # Pinned signal files (README/ARCHITECTURE/etc.) with a tighter budget so
    # they orient the agent without monopolizing the snapshot.
    pinned_to_show = [p for p in pinned[:2] if p not in top_relevant]
    if pinned_to_show:
        parts.append("")
        parts.append("### Project orientation files")
        for rel in pinned_to_show:
            _emit_excerpt(rel, max_lines=25)

    if not top_relevant and not pinned_to_show:
        parts.append("")
        parts.append("(No files in the workspace matched the task keywords.)")

    # Layout sample last — useful overview but loses first if budget is tight.
    layout_max = max(15, int(os.getenv("WORKSPACE_SNAPSHOT_LAYOUT_ENTRIES", "30")))
    layout_sample = sorted(set(files[:300]))[:layout_max]
    parts.append("")
    parts.append(f"### Layout sample ({len(layout_sample)} of {len(files)} files)")
    for path in layout_sample:
        parts.append(f"- {path}")

    rendered = "\n".join(parts).strip()
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 40].rstrip() + "\n… [snapshot truncated]"
    return rendered


# ---------------------------------------------------------------------------
# Public API — evidence for QA review
# ---------------------------------------------------------------------------


def read_artifact_evidence(
    workspace_root: str | None,
    artifact_paths: Iterable[str],
    *,
    max_total_chars: int = 4500,
) -> str:
    """Render what's actually on disk at each claimed artifact path.

    Each artifact is reported as one of:
      ✓ present (size, first N lines)
      ⚠ empty
      ✗ missing
      ⚠ unreadable (with reason)
    """
    if not workspace_root:
        return ""
    paths = [p for p in artifact_paths if p]
    if not paths:
        return ""
    if not os.path.isdir(workspace_root):
        return f"(workspace root {workspace_root!r} not accessible at QA time)"

    parts: list[str] = []
    parts.append(f"Workspace root: {workspace_root}")
    parts.append(f"Artifacts claimed by deliverable: {len(paths)}")
    parts.append("")

    # Defensive de-dup while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for p in paths:
        clean = (p or "").strip().replace("\\", "/")
        if not clean or clean.startswith("/") or ".." in clean.split("/"):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)

    for rel in ordered:
        abs_path = os.path.join(workspace_root, rel)
        try:
            exists = os.path.isfile(abs_path)
        except OSError:
            exists = False
        if not exists:
            parts.append(
                f"✗ MISSING — `{rel}` (no file on disk; deliverable claimed it would exist)"
            )
            continue
        excerpt, size = _read_excerpt(abs_path, max_lines=EVIDENCE_LINES_PER_FILE)
        if excerpt is None:
            parts.append(f"⚠ UNREADABLE — `{rel}` ({size} bytes — read failed)")
            continue
        if size == 0 or not excerpt.strip():
            parts.append(f"⚠ EMPTY — `{rel}` (file exists but contains no content)")
            continue
        parts.append(f"✓ PRESENT — `{rel}` ({size} bytes)")
        parts.append("```")
        parts.append(excerpt)
        parts.append("```")
        parts.append("")

    rendered = "\n".join(parts).strip()
    if len(rendered) > max_total_chars:
        rendered = (
            rendered[: max_total_chars - 40].rstrip() + "\n… [evidence truncated]"
        )
    return rendered
