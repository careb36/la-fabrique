"""``POST /v1/voice/build`` — la fábrica construye lo que pide el chat.

El router de verdad, la app de verdad y un cliente de verdad; lo único falso es
el modelo, que contesta un proyecto fijo. Así se comprueba lo que importa: que
los archivos queden escritos, que el enlace de vista previa los sirva y que un
pedido fallido vuelva como frase (HTTP 200, ``ok: false``) y no como error 500.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FRASE = "quiero que hagas una pagina sencilla en html, css, javascript con la fabrica"

PROYECTO = {
    "files": [
        {
            "path": "index.html",
            "content": '<!doctype html><link rel="stylesheet" href="styles.css">'
            '<h1>Hola</h1><script src="app.js"></script>',
        },
        {"path": "styles.css", "content": "h1 { color: teal; }"},
        {"path": "app.js", "content": "console.log('hola');"},
    ],
    "summary": "una página con un saludo",
}


@pytest.fixture()
def builds(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRICA_BUILDS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def asistente(monkeypatch):
    """El modelo contesta ``PROYECTO``; nada sale a la red."""
    from routers import build as build_router

    monkeypatch.setattr(build_router, "_chat", lambda messages: json.dumps(PROYECTO))
    return build_router


def test_el_pedido_por_chat_escribe_el_proyecto(test_client, builds, asistente):
    respuesta = test_client.post("/v1/voice/build", json={"texto": FRASE})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is True
    assert cuerpo["action"] == "crear_proyecto"
    assert sorted(cuerpo["data"]["files"]) == ["app.js", "index.html", "styles.css"]
    assert cuerpo["data"]["entry"] == "index.html"
    assert cuerpo["data"]["slug"].startswith("pagina-sencilla-html-css")

    carpeta = builds / cuerpo["data"]["slug"]
    assert (carpeta / "index.html").is_file()
    assert "Hola" in (carpeta / "index.html").read_text(encoding="utf-8")


def test_la_vista_previa_sirve_los_archivos_sin_clave(test_client, builds, asistente):
    datos = test_client.post("/v1/voice/build", json={"texto": FRASE}).json()["data"]

    html = test_client.get(datos["preview"])
    css = test_client.get(f"/v1/voice/build/{datos['slug']}/styles.css")

    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "sandbox" in html.headers["content-security-policy"]
    assert "Hola" in html.text
    assert css.status_code == 200
    assert "teal" in css.text


def test_la_raiz_del_proyecto_sirve_el_index(test_client, builds, asistente):
    datos = test_client.post("/v1/voice/build", json={"texto": FRASE}).json()["data"]

    respuesta = test_client.get(f"/v1/voice/build/{datos['slug']}/")

    assert respuesta.status_code == 200
    assert "Hola" in respuesta.text


@pytest.mark.parametrize(
    "ruta",
    [
        "/v1/voice/build/pagina-20260101-120000/../../etc/passwd",
        "/v1/voice/build/../builds/index.html",
        "/v1/voice/build/no-existe/index.html",
        "/v1/voice/build/MAYUS/index.html",
    ],
)
def test_no_se_puede_leer_fuera_del_proyecto(test_client, builds, asistente, ruta):
    assert test_client.get(ruta).status_code == 404


def test_un_pedido_vacio_pide_que_le_digan_que_hacer(test_client, builds, asistente):
    cuerpo = test_client.post("/v1/voice/build", json={"texto": "   "}).json()

    assert cuerpo["ok"] is False
    assert "qué construir" in cuerpo["speech"]
    assert list(builds.iterdir()) == []


def test_un_modelo_que_falla_vuelve_como_frase(test_client, builds, monkeypatch):
    from routers import build as build_router
    from services import codegen

    def revienta(_messages):
        raise codegen.CodegenError("El modelo no devolvió archivos.")

    monkeypatch.setattr(build_router, "_chat", revienta)

    respuesta = test_client.post("/v1/voice/build", json={"texto": FRASE})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["ok"] is False
    assert cuerpo["speech"] == "El modelo no devolvió archivos."
    assert list(builds.iterdir()) == []


def test_un_modelo_que_contesta_cualquier_cosa_no_deja_archivos(
    test_client, builds, monkeypatch
):
    from routers import build as build_router

    monkeypatch.setattr(build_router, "_chat", lambda _m: "no pienso")

    cuerpo = test_client.post("/v1/voice/build", json={"texto": FRASE}).json()

    assert cuerpo["ok"] is False
    assert list(builds.iterdir()) == []


def test_la_carpeta_sale_de_la_variable_de_entorno(
    test_client, builds, asistente, monkeypatch, tmp_path
):
    otro = tmp_path / "otro"
    otro.mkdir()
    monkeypatch.setenv("FABRICA_BUILDS_DIR", str(otro))

    datos = test_client.post("/v1/voice/build", json={"texto": FRASE}).json()["data"]

    assert Path(datos["dir"]).parent == otro


def test_un_id_de_modelo_ausente_se_reintenta_con_el_estrategico(monkeypatch):
    """El catálogo del proveedor cambia: un id que no existe no corta el chat."""
    from routers import build as build_router

    monkeypatch.setenv("AGENT_MODEL", "modelo/que-no-existe")
    monkeypatch.setenv("NEMOTRON_MODEL_STRATEGIC", "modelo/estrategico")
    intentos = []

    class _Cliente:
        def chat(self, messages, model, role, bu_id=None, max_tokens=None, **kwargs):
            intentos.append(model)
            if model != "modelo/estrategico":
                return {"error": "HTTP 404: model not found", "ok": False}
            return {"choices": [{"message": {"content": '{"files": []}'}}]}

    monkeypatch.setattr(build_router, "LLMProxyClient", _Cliente)

    respuesta = build_router._chat([{"role": "user", "content": "hola"}])

    assert respuesta == '{"files": []}'
    assert intentos == ["modelo/que-no-existe", "modelo/estrategico"]


def test_si_ningun_id_sirve_la_frase_dice_cuales_se_probaron(monkeypatch):
    from routers import build as build_router
    from services import codegen

    monkeypatch.setenv("AGENT_MODEL", "modelo/uno")
    monkeypatch.setenv("NEMOTRON_MODEL_STRATEGIC", "modelo/dos")

    class _Cliente:
        def chat(self, messages, model, role, bu_id=None, max_tokens=None, **kwargs):
            return {"error": f"{model}: 404", "ok": False}

    monkeypatch.setattr(build_router, "LLMProxyClient", _Cliente)

    with pytest.raises(codegen.CodegenError) as ctx:
        build_router._chat([{"role": "user", "content": "hola"}])

    # Lo que se dice es corto (sin nombres de host); el detalle va en .detail
    # para quien mira el log o el JSON.
    assert "proxy de modelos" in str(ctx.value)
    assert "modelo/uno" not in str(ctx.value)
    assert "modelo/uno" in ctx.value.detail and "modelo/dos" in ctx.value.detail


def test_el_codegen_no_le_pide_razonamiento_a_nvidia():
    """Razonar antes de escribir estiraba la espera hasta el timeout."""
    from routers.build import _codegen_switches

    assert _codegen_switches("nvidia/nemotron-3-ultra-550b-a55b") == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert _codegen_switches("deepseek-v4-pro") == {}
    assert _codegen_switches("") == {}
