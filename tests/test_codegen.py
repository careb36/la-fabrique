"""El generador de proyectos del backend: JSON del modelo → archivos en disco.

Se prueba sin FastAPI, sin Postgres y sin red: el módulo se carga por ruta (la
carpeta ``services`` del backend importa la base de datos al entrar) y el modelo
es una función que contesta lo que el test quiere. Lo que se comprueba es lo que
puede romperse con un modelo de verdad: JSON sucio, rutas que intentan salir del
proyecto y pedidos que no producen ningún archivo.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEGEN = ROOT / "la-fabrique" / "backend" / "app" / "services" / "codegen.py"

_spec = importlib.util.spec_from_file_location("fabrique_codegen", CODEGEN)
codegen = importlib.util.module_from_spec(_spec)
sys.modules["fabrique_codegen"] = codegen
_spec.loader.exec_module(codegen)


def _reply(files: list[dict], **extra) -> str:
    return json.dumps({"files": files, **extra}, ensure_ascii=False)


class Temp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)


class SlugTest(unittest.TestCase):
    def test_a_sentence_becomes_a_short_slug(self):
        slug = codegen.slugify("Quiero una página sencilla con HTML, CSS y JS")

        self.assertEqual(slug, "pagina-sencilla-html-css")

    def test_filler_words_are_dropped_but_the_topic_survives(self):
        self.assertEqual(
            codegen.slugify("quiero que la fábrica haga una landing de café"),
            "landing-cafe")

    def test_accents_do_not_break_the_url(self):
        self.assertEqual(codegen.slugify("Canción de cuna"), "cancion-cuna")

    def test_a_rioplatense_filler_does_not_open_the_url(self):
        self.assertEqual(codegen.slugify("che, hace una pagina de prueba"),
                         "pagina-prueba")

    def test_an_empty_request_still_has_a_name(self):
        self.assertEqual(codegen.slugify("  ¿? ", fallback="proyecto"), "proyecto")


class SafeRelativeTest(unittest.TestCase):
    def test_a_normal_path_is_kept(self):
        self.assertEqual(codegen.safe_relative("assets/app.js"), "assets/app.js")

    def test_traversal_and_absolute_paths_are_refused(self):
        for name in ("../secret.txt", "assets/../../secret.txt", "/etc/passwd",
                     "C:/Windows/win.ini", "", "   "):
            with self.subTest(name=name):
                self.assertIsNone(codegen.safe_relative(name))


class ParseFilesTest(unittest.TestCase):
    def test_plain_json_is_read(self):
        files = codegen.parse_files(_reply([{"path": "index.html", "content": "<h1/>"}]))

        self.assertEqual(files[0]["path"], "index.html")

    def test_a_fenced_answer_is_read(self):
        answer = "```json\n" + _reply([{"path": "a.js", "content": "1"}]) + "\n```"

        self.assertEqual(codegen.parse_files(answer)[0]["path"], "a.js")

    def test_prose_around_the_object_is_tolerated(self):
        answer = "Claro:\n" + _reply([{"path": "a.js", "content": "1"}]) + "\nÉxitos."

        self.assertEqual(codegen.parse_files(answer)[0]["path"], "a.js")

    def test_the_prose_keeps_the_biggest_answer(self):
        small = _reply([{"path": "a.js", "content": "1"}])
        big = _reply([{"path": "a.js", "content": "x" * 500}])
        answer = small + "\n" + big

        self.assertEqual(len(codegen.parse_files(answer)[0]["content"]), 500)

    def test_an_answer_without_files_is_empty_not_an_error(self):
        self.assertEqual(codegen.parse_files("no pienso hacerlo"), [])


class WriteTest(Temp):
    def test_files_are_written_and_listed(self):
        written = codegen.write_files(self.root, [
            {"path": "index.html", "content": "<h1>hola</h1>"},
            {"path": "css/styles.css", "content": "body{}"},
        ])

        self.assertEqual(written, ["index.html", "css/styles.css"])
        self.assertIn("hola", (self.root / "index.html").read_text())

    def test_a_bad_path_is_skipped_and_the_rest_is_written(self):
        written = codegen.write_files(self.root, [
            {"path": "../fuera.txt", "content": "no"},
            {"path": "dentro.txt", "content": "sí"},
        ])

        self.assertEqual(written, ["dentro.txt"])
        self.assertFalse((self.root.parent / "fuera.txt").exists())

    def test_index_html_is_the_entry_point(self):
        self.assertEqual(
            codegen.pick_entry(["app.js", "index.html", "styles.css"]), "index.html")
        self.assertEqual(codegen.pick_entry(["app.js", "pagina.html"]), "pagina.html")
        self.assertEqual(codegen.pick_entry(["app.js"]), "app.js")


class BuildTest(Temp):
    def test_a_project_is_written_where_the_url_says(self):
        def chat(messages):
            self.assertIn("REQUEST", messages[-1]["content"])
            return _reply([{"path": "index.html", "content": "<h1/>"},
                           {"path": "styles.css", "content": "h1{}"}],
                          summary="una página")

        result = codegen.build(self.root, "una página con html y css", chat)

        self.assertTrue((self.root / result["slug"] / "index.html").is_file())
        self.assertEqual(result["entry"], "index.html")
        self.assertEqual(result["files"], ["index.html", "styles.css"])
        self.assertEqual(result["preview"],
                         f"/v1/voice/build/{result['slug']}/index.html")

    def test_two_requests_on_the_same_second_do_not_overwrite_each_other(self):
        def chat(_messages):
            return _reply([{"path": "index.html", "content": "<h1/>"}])

        first = codegen.build(self.root, "una página", chat, now=1000)
        second = codegen.build(self.root, "una página", chat, now=1000)

        self.assertNotEqual(first["slug"], second["slug"])

    def test_an_answer_without_files_is_a_speakable_error(self):
        with self.assertRaises(codegen.CodegenError) as ctx:
            codegen.build(self.root, "una página", lambda _m: "no sé")

        self.assertIn("no devolvió archivos", str(ctx.exception))

    def test_a_broken_model_is_reported_not_raised_raw(self):
        def chat(_messages):
            raise RuntimeError("connection reset")

        with self.assertRaises(codegen.CodegenError) as ctx:
            codegen.build(self.root, "una página", chat)

        self.assertIn("connection reset", str(ctx.exception))

    def test_an_empty_request_never_reaches_the_model(self):
        called = []
        with self.assertRaises(codegen.CodegenError):
            codegen.build(self.root, "   ", lambda m: called.append(m) or "")

        self.assertEqual(called, [])

    def test_a_prose_answer_is_asked_again_and_the_retry_saves_the_build(self):
        llamadas = []

        def chat(messages):
            llamadas.append(messages)
            if len(llamadas) == 1:
                return "Claro, te armo la página: (sin JSON)"
            return _reply([{"path": "index.html", "content": "<h1/>"}])

        result = codegen.build(self.root, "una página", chat)

        self.assertEqual(result["files"], ["index.html"])
        self.assertEqual(len(llamadas), 2)
        segundo = llamadas[1]
        self.assertEqual(segundo[0]["role"], "system")
        self.assertEqual(segundo[2]["role"], "assistant")
        self.assertIn("SOLO el objeto", segundo[3]["content"])

    def test_a_chat_that_never_complies_stops_at_two_attempts(self):
        llamadas = []

        def chat(messages):
            llamadas.append(messages)
            return "no pienso"

        with self.assertRaises(codegen.CodegenError):
            codegen.build(self.root, "una página", chat)

        self.assertEqual(len(llamadas), codegen.MAX_ATTEMPTS)

    def test_the_files_cap_keeps_a_runaway_answer_out(self):
        files = [{"path": f"f{i}.txt", "content": "x"} for i in range(60)]

        result = codegen.build(self.root, "una página", lambda _m: _reply(files))

        self.assertEqual(len(result["files"]), codegen.MAX_FILES)


class ServePathTest(Temp):
    def setUp(self):
        super().setUp()
        self.project = self.root / "demo-20260101-120000"
        (self.project).mkdir()
        (self.project / "index.html").write_text("<h1/>", encoding="utf-8")
        (self.project / "app.js").write_text("1", encoding="utf-8")
        (self.root / "secreto.txt").write_text("no", encoding="utf-8")

    def test_the_entry_is_index_html_by_default(self):
        target = codegen.serve_path(self.root, "demo-20260101-120000")

        self.assertEqual(target.name, "index.html")

    def test_a_file_inside_the_project_is_served(self):
        target = codegen.serve_path(self.root, "demo-20260101-120000", "app.js")

        self.assertEqual(target.name, "app.js")

    def test_leaving_the_project_is_a_404(self):
        for path in ("../secreto.txt", "../../etc/passwd", "/etc/passwd"):
            with self.subTest(path=path):
                self.assertIsNone(
                    codegen.serve_path(self.root, "demo-20260101-120000", path))

    def test_a_slug_that_is_not_a_project_is_a_404(self):
        for slug in ("no-existe", "../demo-20260101-120000", "demo/../x", ""):
            with self.subTest(slug=slug):
                self.assertIsNone(codegen.serve_path(self.root, slug))


if __name__ == "__main__":
    unittest.main()
