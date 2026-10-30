"""Provenance check: compare two source trees the way a reviewer would.

Two independent measures, because "no shared words at all" is not a reachable
claim for ordinary Python — every QTimer is wired the same way:

* **prose** — comments, docstrings and string literals, 8 words. Any long match
  here means one text was carried over from the other.
* **code** — every token including identifiers, 14 in a row. Short overlaps are
  idioms; fourteen identical tokens in order is a copied block.

Run ``tools/similarity_check.py <other-tree>`` for the report.
"""

from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

WORD = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ_]+")
PROSE_N = 8
CODE_N = 14
SKIP_DIRS = {"__pycache__", ".git", "build", "dist", ".venv", ".venv-remote", "node_modules"}
PATTERNS = ("*.py", "*.md", "*.txt", "*.json")
CODE_EXTS = {".py"}
PROSE_MIN_WORDS = 6
_DOC_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass
class Report:
    left_files: int = 0
    right_files: int = 0
    prose_shared: list[str] = field(default_factory=list)
    code_shared: list[str] = field(default_factory=list)
    left_prose: int = 0
    right_prose: int = 0
    left_code: int = 0
    right_code: int = 0

    @property
    def identical(self) -> bool:
        return not self.prose_shared and not self.code_shared

    def summary(self) -> str:
        return (
            f"{self.left_files} archivos propios / {self.right_files} del otro árbol · "
            f"prosa: {len(self.prose_shared)} coincidencias de {PROSE_N} palabras · "
            f"código: {len(self.code_shared)} bloques de {CODE_N} tokens"
        )


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    words = WORD.findall(text.lower())
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def prose_of(path: Path) -> str:
    """Comments, docstrings and string literals; whole text for non-Python."""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix not in CODE_EXTS:
        return raw
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return raw
    pieces: list[str] = [" ".join(ast.get_docstring(node, clean=True).split())
                        for node in ast.walk(tree) if isinstance(node, _DOC_NODES)
                        and ast.get_docstring(node, clean=True)]
    try:
        for token in tokenize.generate_tokens(io.StringIO(raw).readline):
            if token.type == tokenize.COMMENT:
                pieces.append(token.string)
            elif (
                token.type == tokenize.STRING
                and "://" not in token.string
                and len(WORD.findall(token.string)) >= PROSE_MIN_WORDS
            ):
                # Short literals are keys, routes and host lists ("type",
                # "127.0.0.1"): vocabulary every program shares, not prose.
                pieces.append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pieces.append(raw)  # Unparsable file: fall back to the whole text.
    return "\n".join(pieces)


def _iter_files(root: Path):
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        folder = Path(current)
        for name in filenames:
            path = folder / name
            if any(path.match(pattern) for pattern in PATTERNS):
                yield path


def _collect(root: Path) -> tuple[int, set, set, int, int]:
    files = 0
    prose: set = set()
    code: set = set()
    prose_count = 0
    code_count = 0
    for path in _iter_files(root):
        files += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        stamps = shingles(text, CODE_N)
        code |= stamps
        code_count += len(stamps)
        if path.suffix in CODE_EXTS:
            text = prose_of(path)
        stamps = shingles(text, PROSE_N)
        prose |= stamps
        prose_count += len(stamps)
    return files, prose, code, prose_count, code_count


def compare(left: Path, right: Path) -> Report:
    report = Report()
    report.left_files, left_prose, left_code, report.left_prose, report.left_code = _collect(left)
    report.right_files, right_prose, right_code, report.right_prose, report.right_code = _collect(right)
    report.prose_shared = [" ".join(item) for item in sorted(left_prose & right_prose)]
    report.code_shared = [" ".join(item) for item in sorted(left_code & right_code)]
    return report
