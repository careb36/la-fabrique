"""Serve the factory's own web UI from the backend.

The React app in ``frontend/`` is the product's interface and talks to
this same API, so the built ``dist`` can be served same-origin and the browser needs no dev server. Building is a packaging
step, not a runtime one — when ``dist`` is absent the API keeps working and
``/`` explains how to build it instead of returning a bare 404.

The shell is returned from a middleware, not from a catch-all route, on
purpose. A catch-all would match every path, and the metrics would then label
scanner traffic as if it were the app; from here only paths the routers truly
did not answer reach the shell, so ``unmatched`` keeps meaning what it says.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# Paths the SPA must never swallow: they belong to the API or its docs.
_RESERVED = (
    "v1/",
    "health",
    "metrics",
    "docs",
    "redoc",
    "openapi.json",
    "assets/",
)


def dist_dir() -> Path:
    """Where the built UI lives: ``FABRICA_UI_DIST`` or ``frontend/dist``."""
    override = os.getenv("FABRICA_UI_DIST")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


_MISSING = """<!doctype html>
<html lang="es"><meta charset="utf-8"><title>Fábrica — interfaz sin compilar</title>
<style>
 body {{ font: 15px/1.6 system-ui, sans-serif; max-width: 40rem; margin: 12vh auto;
         padding: 0 1.5rem; color: #1b1b1f; background: #faf7f2; }}
 code {{ background: #eee9e0; padding: .15rem .35rem; border-radius: 4px; }}
 h1 {{ font-size: 1.35rem; }}
</style>
<h1>La interfaz no está compilada</h1>
<p>El backend está funcionando, pero no encuentra <code>frontend/dist</code>.</p>
<p>Compílala una vez con <code>npm ci &amp;&amp; npm run build</code> dentro de
<code>frontend</code>.</p>
<p>Mientras tanto, la API responde en <a href="/docs">/docs</a>.</p>
</html>"""


def _is_reserved(path: str) -> bool:
    return path.startswith(_RESERVED)


def _looks_like_a_file(path: str) -> bool:
    """``wp-login.php``, ``.env``, ``.git/config``: answered with a 404.

    A single-page app answers any path with its shell, which would turn every
    scan for a leaked file into a 200 and hide the noise in the metrics. Only
    paths shaped like an app route get the shell.
    """
    return any("." in segment for segment in path.split("/") if segment)


def mount_ui(app: FastAPI) -> None:
    """Attach the SPA to *app*: hashed assets plus an index.html fallback."""
    dist = dist_dir()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")

    @app.middleware("http")
    async def serve_ui(request: Request, call_next):
        response = await call_next(request)
        if response.status_code != 404 or request.method not in ("GET", "HEAD"):
            return response
        path = request.url.path.lstrip("/")
        # A file shipped at the root of the bundle (favicon, manifest) wins.
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        if _is_reserved(path) or _looks_like_a_file(path):
            return response
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(_MISSING, status_code=503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
