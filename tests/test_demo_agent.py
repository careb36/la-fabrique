"""El agente de la demo: escribe, ejecuta y prueba — sin creerse al modelo.

Lo que se prueba aquí es el bucle, no el modelo: que el JSON del protocolo se
lea aunque venga con prosa, que el agente no pueda escribir fuera de su
directorio, y que un fallo de las pruebas vuelva al modelo con la salida real en
vez de darse por bueno.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.coding_agent import (CodingAgent, parse_reply, run_tests,   # noqa: E402
                               write_files, _safe_path)


class ParseReplyTest(unittest.TestCase):
    def test_a_plain_object_is_read(self):
        plan = parse_reply('{"files": [{"path": "a.py", "content": "x"}]}')

        self.assertEqual(plan["files"][0]["path"], "a.py")

    def test_a_json_fence_is_read(self):
        plan = parse_reply('```json\n{"summary": "ok", "files": []}\n```')

        self.assertEqual(plan["summary"], "ok")

    def test_prose_around_the_object_is_tolerated(self):
        plan = parse_reply('Claro, aquí va:\n{"summary": "hecho", "files": []}\n'
                           'Suerte con el proyecto.')

        self.assertEqual(plan["summary"], "hecho")

    def test_an_answer_without_json_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_reply("no pienso contestar en JSON")


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_relative_path_lands_inside(self):
        target = _safe_path(self.root, "pkg/mod.py")

        self.assertEqual(target, (self.root / "pkg/mod.py").resolve())

    def test_a_path_that_escapes_is_refused(self):
        for name in ("../fuera.py", "pkg/../../fuera.py", "/etc/passwd"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    _safe_path(self.root, name)

    def test_written_files_are_reported_relative(self):
        written = write_files(self.root, [
            {"path": "a.py", "content": "print(1)"},
            {"path": "d/b.py", "content": "print(2)"},
        ])

        self.assertEqual(written, ["a.py", "d/b.py"])
        self.assertEqual((self.root / "a.py").read_text().strip(), "print(1)")


class RunTestsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_passing_suite_passes(self):
        write_files(self.root, [{"path": "test_ok.py", "content":
                                 "import unittest\n\n\n"
                                 "class T(unittest.TestCase):\n"
                                 "    def test_uno(self):\n"
                                 "        self.assertEqual(1, 1)\n"}])

        ok, output = run_tests(self.root)

        self.assertTrue(ok, output)

    def test_a_failing_suite_fails_and_says_why(self):
        write_files(self.root, [{"path": "test_mal.py", "content":
                                 "import unittest\n\n\n"
                                 "class T(unittest.TestCase):\n"
                                 "    def test_uno(self):\n"
                                 "        self.assertEqual(1, 2)\n"}])

        ok, output = run_tests(self.root)

        self.assertFalse(ok)
        self.assertIn("FAILED", output)


class OfflineLoopTest(unittest.TestCase):
    """La grabación hace el recorrido completo: una ronda falla, la otra arregla."""

    def test_the_agent_iterates_until_the_tests_pass(self):
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            report = CodingAgent(offline=True, log=lines.append).run(
                "slugify", Path(tmp), rounds=3)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["rounds"], 2)
        self.assertTrue(any("FALLAN" in line for line in lines))
        self.assertTrue(any("pruebas: OK" in line for line in lines))

    def test_one_round_is_not_enough_and_the_agent_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = CodingAgent(offline=True, log=lambda *a: None).run(
                "slugify", Path(tmp), rounds=1)

        self.assertFalse(report["ok"])
        self.assertIn("FAILED", report["output"])


if __name__ == "__main__":
    unittest.main()


def test_the_model_written_tests_run_without_the_parents_secrets(monkeypatch):
    """A test file the model wrote cannot read the keys this process holds."""
    from demo import coding_agent

    monkeypatch.setenv("NEBIUS_API_KEY", "nvapi-must-not-leak")
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "test_env.py").write_text(
            "import os, unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_no_key(self):\n"
            "        self.assertNotIn('NEBIUS_API_KEY', os.environ)\n",
            encoding="utf-8",
        )
        ok, output = coding_agent.run_tests(root)
    assert ok, output
