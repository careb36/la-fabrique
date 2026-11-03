"""What QA is shown of a delivery: every file, within a fixed size.

The board keeps a deliverable comment of at most 4000 characters and the
review prompt used to show the first 3000 of it. A delivery of three files
reached QA as one file and part of the next, so QA asked for the "missing"
files, and the rework regenerated all of them: the most expensive call in the
loop, spent on content that was already written and verified.

``build`` lists every file the delivery wrote (path, lines, bytes), then an
excerpt of each one, sharing ``DIGEST_CHARS`` between them; a file that does
not fit says how many lines were left out, so a cut is never read as a
missing part. Each file keeps its ``# Artifact: <path>`` heading, which the
board and the e2e read. The full files are on disk and in the run's artifact.
"""

from __future__ import annotations

DIGEST_CHARS = 3800
HEADER = "Files written"
MIN_EXCERPT_CHARS = 120
NOTE = (
    "\n\nThe files listed above were written to the project and checked by the "
    "Verifier. Long files are shown as excerpts by the system: a file cut here "
    "is not a missing part, so do not ask for content only because this view "
    "leaves it out. Judge whether the work meets the task."
)


def is_digest(text: str) -> bool:
    return (text or "").startswith(HEADER)


def _excerpt(content: str, budget: int) -> str:
    if len(content) <= budget:
        return content
    kept: list[str] = []
    used = 0
    lines = content.splitlines()
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    left = len(lines) - len(kept)
    return "\n".join(kept) + f"\n[... {left} more line(s) not shown here]"


def build(
    targets: list[dict[str, str]], prose: str = "", limit: int = DIGEST_CHARS
) -> str:
    """The digest of a delivery's files, at most about ``limit`` characters."""
    files = [
        (t.get("path") or "artifact", (t.get("content") or "").strip("\n"))
        for t in targets
    ]
    index = [f"{HEADER} ({len(files)}):"]
    for path, content in files:
        lines = content.count("\n") + 1 if content else 0
        index.append(f"- {path} ({lines} lines, {len(content.encode('utf-8'))} bytes)")
    head = "\n".join(index)
    prose = (prose or "").strip()
    if prose:
        prose = prose[:400]
        head += f"\n\nDeveloper's note: {prose}"
    headings = sum(len(f"\n\n# Artifact: {path}\n\n") for path, _ in files)
    room = limit - len(head) - headings
    per_file = max(MIN_EXCERPT_CHARS, room // max(1, len(files)))
    sections = [head]
    for path, content in files:
        sections.append(f"# Artifact: {path}\n\n{_excerpt(content, per_file)}")
    return "\n\n".join(sections)
