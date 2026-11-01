import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402 - after the path setup above


@pytest.fixture(autouse=True)
def _no_downloaded_kokoro(tmp_path_factory, monkeypatch):
    """A Kokoro voice downloaded on this machine must not change which
    speaker the tests get; a test that wants one points B1_KOKORO_DIR at it."""
    monkeypatch.setenv("B1_KOKORO_DIR", str(tmp_path_factory.mktemp("no-kokoro")))
