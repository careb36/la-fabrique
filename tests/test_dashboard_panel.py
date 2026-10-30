"""Guards for the assistant's web panel.

The panel is one static page served by ``dashboard/server.py``; a renamed id or
a tab dropped from the markup still renders, it just stops working, and only at
runtime. These checks keep the contract between the HTML and its script honest.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "profesor3" / "dashboard" / "static"
PAGE = STATIC / "app.html"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parts(page: str) -> tuple[str, str]:
    markup, script = page.split("<script>", 1)
    return markup, script.rsplit("</script>", 1)[0]


def test_the_panel_ships_without_a_second_copy_of_the_factory():
    """The factory tab embeds the factory's own React UI, it does not re-draw it."""
    assert not (STATIC / "fabrica.html").exists()


def test_every_element_the_script_looks_up_exists(parts):
    markup, script = parts
    defined = set(re.findall(r'id="([^"]+)"', markup))
    used = set(re.findall(r"""getElementById\(['"]([^'"]+)['"]\)""", script))
    # renderCore() probes an optional desktop-only element.
    missing = used - defined - {"core-visual"}
    assert not missing, f"ids sin elemento: {sorted(missing)}"


def test_the_navigation_sits_in_the_top_bar(parts):
    markup, _ = parts
    header = markup.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
    assert '<nav class="nav" id="nav"' in header
    assert header.count('data-view="') == 4
    for view in ("asistente", "fabrica", "controles", "ajustes"):
        assert f'data-view="{view}"' in header


def test_the_utilities_drawer_is_outside_the_work_area(parts):
    markup, _ = parts
    assert markup.index('id="sidebar"') < markup.index('<div class="main">')


def test_the_inspector_opens_as_a_drawer(page):
    """One behaviour at every width; the old wide-screen branch is gone."""
    assert "inspector-hidden" in page  # the class survives for the stylesheet
    assert "inspector-open" in page
    body = page.split("function toggleInspector(force) {", 1)[1].split("\n}\n", 1)[0]
    assert "innerWidth" not in body


def test_the_view_title_moved_to_the_status_bar(parts):
    markup, _ = parts
    footer = markup.split('<footer class="app-footer"', 1)[1].split("</footer>", 1)[0]
    assert 'id="workspace-title"' in footer
    assert 'id="workspace-sub"' in footer


def test_the_factory_tab_frames_the_factory(page):
    """The tab loads the factory's own UI through the doorway, not a mock-up."""
    assert 'id="fabrica-frame"' in page
    assert "frame.src = '/fabrica'" in page
    assert "?token=" in page
