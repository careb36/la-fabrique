"""Serving the product's own UI from the backend.

The packaged product is one process: the React app and the API share an
origin, so the browser needs no dev server and no port configuration. The
fallback must not swallow API routes, and a machine without the built UI has
to be told how to build it rather than shown a bare 404.
"""

from pathlib import Path

import pytest
import ui_static
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>fábrica</title>", "utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    (dist / "fabrique-icon.svg").write_text("<svg/>", "utf-8")
    return dist


@pytest.fixture
def client(tmp_path, monkeypatch):
    dist = _dist(tmp_path)
    monkeypatch.setenv("FABRICA_UI_DIST", str(dist))

    app = FastAPI()

    @app.get("/v1/capabilities")
    async def capabilities():
        return {"auth_required": True}

    ui_static.mount_ui(app)
    return TestClient(app)


def test_the_root_serves_the_shell(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "fábrica" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_a_deep_link_serves_the_shell_so_the_router_can_take_over(client):
    assert client.get("/sprints/12/tasks/3").text == client.get("/").text


def test_real_files_win_over_the_shell(client):
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log(1)"


def test_api_routes_are_not_swallowed(client):
    response = client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {"auth_required": True}


def test_a_path_outside_the_bundle_is_not_served(client):
    response = client.get("/../../etc/passwd")

    assert response.status_code == 200
    assert "fábrica" in response.text


def test_a_file_at_the_root_of_the_bundle_is_served(client):
    response = client.get("/fabrique-icon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"


def test_a_scan_for_a_leaked_file_is_a_404_not_the_shell(client):
    """Otherwise every scanner hit is a 200 and the metrics stop meaning anything."""
    for path in ("/wp-login.php", "/.env", "/.git/config", "/backup.sql"):

        assert client.get(path).status_code == 404, path


def test_without_a_build_it_explains_how_to_build(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRICA_UI_DIST", str(tmp_path / "missing"))
    app = FastAPI()
    ui_static.mount_ui(app)

    response = TestClient(app).get("/")

    assert response.status_code == 503
    assert "npm run build" in response.text
