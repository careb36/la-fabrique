"""Turning a request into files that exist.

The factory's agents answer in text. A person who types "hacé una página con
html, css y javascript" is not asking for a description of a page: they expect
files they can open. This service is the bridge — the model is asked for a JSON
file list, and the only thing trusted afterwards is that JSON:

* every path is validated (relative, no ``..``, nothing absolute),
* everything is written inside one directory per project,
* the directory is served read-only by ``/v1/voice/build/<slug>/…``.

The protocol is the same one the coding-agent demo (``demo/coding_agent.py`` on
the fusion branch) speaks, so a model that behaves for the demo behaves here.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from pathlib import Path

MAX_FILES = 40
MAX_FILE_CHARS = 200_000
# Whole files do not fit in a provider's default completion budget; a truncated
# answer is invalid JSON and looks like a broken model.
MAX_ANSWER_TOKENS = 8192
# One repair turn: the second answer is asked for in the strictest possible way.
MAX_ATTEMPTS = 2

PROTOCOL = """\
You are the Developer agent of La Fabrique, a software factory. You are given a
request in Spanish; turn it into a small, complete, working project.

Answer with ONE JSON object and nothing else — no prose, no code fences:

{"files": [{"path": "index.html", "content": "the whole file"}],
 "summary": "one sentence in Spanish saying what you built"}

Rules:
- Python/HTML/CSS/JS standard features only. No CDNs, no network calls, no
  build step: whatever you write must work when the files are opened.
- If the request is a web page: `index.html` is the entry point, and it links
  the other files by relative path (styles.css, app.js).
- Write real, complete files — no placeholders, no "TODO", no truncation.
- Paths are relative, inside the project: no absolute paths, no `..`.
- Keep it small enough to read in one screen per file: at most three files,
  none longer than about 120 lines.
"""


class CodegenError(RuntimeError):
    """The model did not produce a usable project; the message is speakable."""


# Filler that says nothing about the project: "quiero que hagas una página".
_FILLER = {
    "quiero",
    "necesito",
    "que",
    "me",
    "hagas",
    "haga",
    "hacer",
    "hace",
    "hacé",
    "crees",
    "cree",
    "crear",
    "crea",
    "creá",
    "fabricá",
    "fabrique",
    "un",
    "una",
    "unos",
    "unas",
    "el",
    "la",
    "los",
    "las",
    "de",
    "del",
    "con",
    "para",
    "por",
    "favor",
    "en",
    "y",
    "o",
    "mi",
    "mio",
    "fábrica",
    "fabrica",
    "fábrica,",
    "che",
    "dale",
    "oye",
    "ey",
    "bueno",
    "hola",
    "amigo",
    "porfa",
}


def slugify(text: str, fallback: str = "proyecto") -> str:
    """A short URL-safe name for the project: the words that describe it."""
    plain = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    plain = re.sub(r"[^a-zA-Z0-9]+", "-", plain).strip("-").lower()
    words = [word for word in plain.split("-") if word]
    meaningful = [word for word in words if word not in _FILLER]
    # The first words describe the request; a whole sentence makes a silly URL.
    short = "-".join((meaningful or words)[:4])
    return short[:40].strip("-") or fallback


def safe_relative(name: str) -> str | None:
    """A relative path inside the project, or ``None`` if it tries to leave."""
    raw = str(name or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def parse_files(text: str) -> list[dict]:
    """The ``files`` list from the model's answer, tolerating fences and prose.

    ``json.loads`` on the whole reply first (what the protocol asks for), then
    the largest object that decodes — models that add a greeting still work.
    """
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    candidates: list[dict] = []
    try:
        candidates.append(json.loads(raw))
    except ValueError:
        decoder = json.JSONDecoder()
        for start in (i for i, ch in enumerate(raw) if ch == "{"):
            try:
                obj, _ = decoder.raw_decode(raw[start:])
            except ValueError:
                continue  # not a JSON object at this brace; try the next one
            if isinstance(obj, dict):
                candidates.append(obj)
    best: list[dict] = []
    for obj in candidates:
        files = obj.get("files")
        if isinstance(files, list) and files and _score(files) >= _score(best):
            best = [item for item in files if isinstance(item, dict)]
    return best


def _score(files: list) -> int:
    return sum(
        len(str(item.get("content") or "")) for item in files if isinstance(item, dict)
    )


def write_files(root: Path, files: list[dict]) -> list[str]:
    """Write the project; returns the paths actually written, relative to root."""
    written: list[str] = []
    for item in files[:MAX_FILES]:
        relative = safe_relative(str(item.get("path") or ""))
        if relative is None:
            continue
        content = str(item.get("content") or "")[:MAX_FILE_CHARS]
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            content if content.endswith("\n") else content + "\n", encoding="utf-8"
        )
        written.append(relative)
    return written


def pick_entry(written: list[str]) -> str:
    """The file to open: ``index.html`` if it exists, else the first one."""
    for name in written:
        if name.lower() == "index.html":
            return name
    for name in written:
        if name.lower().endswith(".html"):
            return name
    return written[0] if written else ""


def serve_path(root: Path, slug: str, file_path: str = "") -> Path | None:
    """The file a preview request asks for, or ``None`` if it is not inside.

    The URL is opened by a browser, so it carries no key: this is the check that
    keeps a crafted ``/build/<slug>/../../.env`` from reading anything but the
    project's own files.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", slug or ""):
        return None
    project = (root / slug).resolve()
    if not project.is_dir():
        return None
    # An empty path means the entry point; an *invalid* path is a 404 — falling
    # back to index.html would answer a traversal attempt with a 200.
    relative = safe_relative(file_path) if file_path else "index.html"
    if relative is None:
        return None
    target = (project / relative).resolve()
    if project not in target.parents or not target.is_file():
        return None
    return target


def build(root: Path, request_text: str, chat, *, now: float | None = None) -> dict:
    """Ask the model for the project and write it under *root*.

    ``chat`` is a callable ``(messages) -> str`` (the router passes the LLM
    proxy client). Failures raise :class:`CodegenError` with a sentence the
    assistant can read out loud: "no pude" is a result, not a stack trace.
    """
    request_text = str(request_text or "").strip()
    if not request_text:
        raise CodegenError("El pedido está vacío: decime qué querés construir.")

    started = time.monotonic()
    messages = [
        {"role": "system", "content": PROTOCOL},
        {"role": "user", "content": f"REQUEST\n{request_text}"},
    ]
    files: list[dict] = []
    answer = ""
    for _attempt in range(MAX_ATTEMPTS):
        try:
            answer = chat(messages)
        except CodegenError:
            raise
        except Exception as exc:
            raise CodegenError(f"No pude hablar con el modelo: {exc}") from exc

        files = parse_files(answer)
        if files:
            break
        # An answer with prose or a cut-off JSON is common enough to be worth
        # one stricter request rather than telling the person to try again.
        messages = messages[:2] + [
            {"role": "assistant", "content": answer[:2000]},
            {
                "role": "user",
                "content": "Eso no es JSON válido. Devolvé SOLO el "
                'objeto {"files": [...]} completo, sin '
                "texto alrededor ni bloques de código.",
            },
        ]

    if not files:
        raise CodegenError(
            "El modelo no devolvió archivos: contestó algo que no es el proyecto. "
            "Probá de nuevo o pedí algo más concreto."
        )

    # A random part keeps the preview URL from being guessed: the folder name
    # is otherwise the request's first words and the second it was built.
    stamp = (
        time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + secrets.token_hex(4)
    )
    base = slugify(request_text)
    slug, attempt = f"{base}-{stamp}", 1
    while (root / slug).exists():
        attempt += 1
        slug = f"{base}-{stamp}-{attempt}"
    destination = root / slug
    destination.mkdir(parents=True, exist_ok=True)

    written = write_files(destination, files)
    if not written:
        raise CodegenError(
            "Los archivos que propuso el modelo no tenían nombres válidos: no "
            "escribí nada. Probá de nuevo."
        )
    entry = pick_entry(written)
    return {
        "slug": slug,
        "dir": str(destination),
        "files": written,
        "entry": entry,
        "preview": f"/v1/voice/build/{slug}/{entry}",
        "seconds": round(time.monotonic() - started, 1),
    }
