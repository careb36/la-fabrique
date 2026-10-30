"""The assistant must not quote the assistant it replaces.

The last two tests are the control group: the same checker has to *find* a copy
when there is one, otherwise a clean result proves nothing.
"""

from pathlib import Path

import pytest

from b1.originality import compare

ROOT = Path(__file__).resolve().parents[1]
OTHER = ROOT.parent / "profesor3"
needs_other = pytest.mark.skipif(not OTHER.exists(), reason="arbol de referencia no presente")


@needs_other
def test_no_shared_phrasing_with_the_previous_assistant():
    report = compare(ROOT / "b1", OTHER)
    assert report.left_prose > 500 and report.left_code > 500, report.summary()
    assert report.prose_shared == [], report.summary()
    assert report.code_shared == [], report.summary()
    assert report.identical


def test_a_tree_compared_with_itself_overlaps_completely(tmp_path):
    (tmp_path / "uno.py").write_text(
        '"""Una frase larga que sirve de control para la prueba."""\n', encoding="utf-8"
    )
    report = compare(tmp_path, tmp_path)
    assert report.identical is False
    assert report.prose_shared


@needs_other
def test_the_checker_notices_a_copied_paragraph(tmp_path):
    prompts = OTHER / "core" / "prompt.txt"
    if not prompts.exists():
        pytest.skip("no hay prompt.txt en el arbol de referencia")
    copied = prompts.read_text(encoding="utf-8", errors="ignore")[:900]
    (tmp_path / "copia.py").write_text(f'NOTE = """{copied}"""\n', encoding="utf-8")

    report = compare(tmp_path, OTHER)
    assert report.prose_shared, "el chequeo no detecto un parrafo copiado"
