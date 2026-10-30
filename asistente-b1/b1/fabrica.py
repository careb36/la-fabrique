"""The factory door: HTTP client, spoken guide and the tools the model may call.

La Fabrique exposes ``/v1/voice/*`` (status, one-command vocabulary, instant
build) and every answer already contains a sentence meant to be said out loud.
That is the contract this module leans on: the model does not summarize the
factory, it *relays* it, and the numbers travel separately in ``data``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import net
from .i18n import normalize, t
from .tools import ToolRegistry, object_schema

GUIDE_TITLE = {"es": "LA FÁBRICA — LO QUE PODÉS PEDIR", "en": "THE FACTORY — WHAT YOU CAN ASK FOR"}

GUIDE = {
    "es": (
        "La fábrica es un equipo de agentes que escribe software por vos: un jefe de "
        "producto que ordena el pedido, un arquitecto que decide la estructura, un "
        "scrum que parte el trabajo, desarrolladores que escriben y un QA que revisa "
        "antes de entregar.\n\n"
        "Se maneja hablando. Podés pedirme el estado («¿cómo va la fábrica?»), el "
        "equipo, que planee un sprint a partir de una idea, que lo despache, que lo "
        "pause, que lo reanude, y que apruebe o rechace una entrega.\n\n"
        "Y podés hablarle a un agente por su nombre: «decile al QA que revise el "
        "login», «encargale al arquitecto el modelo de datos». Eso le deja una "
        "tarjeta asignada en el tablero.\n\n"
        "Un sprint creado por voz nace en pausa a propósito: lo escuchás, y recién "
        "cuando decís «reanudá» empieza a trabajar. Así nada se dispara por un mal "
        "entendido del micrófono.\n\n"
        "También construyo al instante, sin sprint ni reunión: «armá una página con "
        "precios», «haceme una calculadora de propinas», «un formulario de contacto». "
        "Eso sale en segundos y te lo abro en el navegador.\n\n"
        "Para lo demás necesito el backend de la fábrica encendido y la clave de voz "
        "cargada en mis ajustes; si falta algo, te lo digo en vez de fallar en silencio."
    ),
    "en": (
        "The factory is a team of agents that writes software for you: a product "
        "owner who scopes the request, an architect who decides the structure, a "
        "scrum that splits the work, developers who write and a QA that reviews "
        "before delivery.\n\n"
        "You drive it by talking. Ask me for the status, the team, to plan a sprint "
        "from an idea, to dispatch it, to pause it, to resume it, and to approve or "
        "reject a delivery.\n\n"
        "You can also talk to an agent by name: “tell QA to review the login”, "
        "“give the architect the data model”. That leaves a card assigned on the "
        "board.\n\n"
        "A sprint created by voice is born paused on purpose: you hear it, and only "
        "when you say “resume” does work start. Nothing fires on a misheard word.\n\n"
        "I also build on the spot, with no sprint and no meeting: “a page with "
        "pricing”, “a tip calculator”, “a contact form”. That lands in seconds and I "
        "open it in your browser.\n\n"
        "For everything else I need the factory backend running and the voice key "
        "in my settings; if something is missing I say so instead of failing quietly."
    ),
}

# Said out loud at startup, word for word, so the voice and the panel agree.
# Nothing here goes beyond what GUIDE explains: the assistant does not promise
# capabilities the tools do not have.
SPOKEN_SUMMARY = {
    "es": (
        "La fábrica está conectada. Es un equipo de agentes que escribe software "
        "por vos, y se maneja hablando: estado, planear un sprint, despachar, "
        "pausar, reanudar, aprobar, encargarle algo a un agente. Un sprint que creo "
        "por voz queda en pausa hasta que me digas reanudá. Y si querés algo chico y "
        "ya, pedime que arme una página o una calculadora. Te dejé la lista en "
        "pantalla."
    ),
    "en": (
        "The factory is connected. It is a team of agents that writes software for "
        "you, and you drive it by talking: status, plan a sprint, dispatch, pause, "
        "resume, approve, hand a task to an agent. A sprint I create by voice stays "
        "paused until you say resume. And if you want something small right now, ask "
        "me to build a page or a calculator. The list is on screen."
    ),
}


def guide_text(language: str = "es") -> str:
    return GUIDE.get(_lang(language), GUIDE["es"])


def guide_title(language: str = "es") -> str:
    return GUIDE_TITLE.get(_lang(language), GUIDE_TITLE["es"])


def spoken_summary(language: str = "es") -> str:
    return SPOKEN_SUMMARY.get(_lang(language), SPOKEN_SUMMARY["es"])


def _lang(language: str | None) -> str:
    return normalize(language)


class FactoryError(Exception):
    """The factory is unreachable or answered something unusable."""


@dataclass
class FactoryAnswer:
    """One factory reply: what to say, plus the structured data behind it."""

    ok: bool
    action: str
    speech: str
    data: dict[str, Any]

    def __bool__(self) -> bool:
        return self.ok


class FactoryClient:
    """Thin, dependency-free client for the factory's voice façade."""

    def __init__(
        self,
        base_url: str,
        voice_key: str = "",
        *,
        company_id: int | None = None,
        language: str = "es",
        timeout: float = 30.0,
        build_timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.voice_key = voice_key.strip()
        self.company_id = company_id
        self.language = _lang(language)
        self.timeout = timeout
        self.build_timeout = build_timeout
        # An action that changes work in the factory, waiting for the person
        # to confirm it (see CONFIRM_ACTIONS and Assistant.handle).
        self.pending: dict | None = None

    # -- transport ----------------------------------------------------------
    def _call(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v not in (None, "")}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        headers = {"Accept": "application/json"}
        if self.voice_key:
            headers["X-Voice-Key"] = self.voice_key
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with net.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise FactoryError(t(self.language, "factory.key_rejected")) from None
            if exc.code == 503:
                raise FactoryError(t(self.language, "factory.no_voice")) from None
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 - the code alone is informative.
                pass
            raise FactoryError(
                t(self.language, "factory.http", code=exc.code, path=path, detail=detail)
            ) from None
        except urllib.error.URLError as exc:
            raise FactoryError(
                t(self.language, "factory.unreachable", url=self.base_url, reason=exc.reason)
            ) from None
        except TimeoutError:
            raise FactoryError(
                t(
                    self.language,
                    "factory.timeout",
                    seconds=(timeout or self.timeout),
                )
            ) from None

        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            head = raw.decode("utf-8", "replace").strip()[:60]
            raise FactoryError(
                t(
                    self.language,
                    "factory.not_json",
                    url=f"{self.base_url}{path}",
                    head=repr(head),
                )
            ) from None
        if not isinstance(body, dict):
            raise FactoryError(t(self.language, "factory.unexpected"))
        return body

    @staticmethod
    def _answer(body: dict, fallback_action: str) -> FactoryAnswer:
        return FactoryAnswer(
            ok=bool(body.get("ok")),
            action=str(body.get("action") or fallback_action),
            speech=str(body.get("speech") or ""),
            data=body.get("data") if isinstance(body.get("data"), dict) else {},
        )

    # -- operations ---------------------------------------------------------
    def ping(self) -> tuple[bool, str]:
        try:
            body = self._call("GET", "/v1/voice/ping", timeout=8.0)
        except FactoryError as exc:
            return False, str(exc)
        return bool(body.get("ok")), str(
            body.get("speech") or t(self.language, "factory.connected")
        )

    def status(self, company_id: int | None = None) -> FactoryAnswer:
        body = self._call(
            "GET",
            "/v1/voice/status",
            params={
                "company_id": company_id or self.company_id,
                "language": self.language,
            },
        )
        return self._answer(body, "estado")

    def command(
        self,
        action: str,
        *,
        text: str | None = None,
        sprint_id: int | None = None,
        run_id: int | None = None,
        sprint_name: str | None = None,
        scope_size: str | None = None,
        feedback: str | None = None,
        agent: str | None = None,
        company_id: int | None = None,
    ) -> FactoryAnswer:
        payload: dict[str, Any] = {
            "action": action,
            "language": self.language,
            "company_id": company_id or self.company_id,
        }
        for key, value in {
            "text": text,
            "sprint_id": sprint_id,
            "run_id": run_id,
            "sprint_name": sprint_name,
            "scope_size": scope_size,
            "feedback": feedback,
            "agent": agent,
        }.items():
            if value not in (None, ""):
                payload[key] = value
        body = self._call("POST", "/v1/voice/command", payload)
        return self._answer(body, action)

    def build(self, texto: str, nombre: str | None = None) -> FactoryAnswer:
        payload: dict[str, Any] = {"texto": texto, "language": self.language}
        if nombre:
            payload["nombre"] = nombre
        body = self._call(
            "POST", "/v1/voice/build", payload, timeout=self.build_timeout
        )
        answer = self._answer(body, "crear_proyecto")
        slug = answer.data.get("slug")
        if answer.ok and slug:
            answer.data["url"] = self.preview_url(str(slug))
        return answer

    def preview_url(self, slug: str) -> str:
        return f"{self.base_url}/v1/voice/build/{urllib.parse.quote(slug)}/index.html"


# ---------------------------------------------------------------------------
# Tools the model may call
# ---------------------------------------------------------------------------


def _description(key: str, language: str) -> str:
    entries = DESCRIPTIONS[key]
    return entries[normalize(language)]


DESCRIPTIONS = {
    "status": {
        "es": "Estado de la fábrica: qué sprint está en curso, cuántas tareas hay en "
        "cada etapa y qué está esperando aprobación. Usala cuando pregunten cómo va todo.",
        "en": "Factory status: which sprint is running, how many tasks sit in each "
        "stage and what is waiting for approval. Use it when asked how things are going.",
    },
    "command": {
        "es": "Ejecuta una instrucción de la fábrica. Verbos válidos: estado, sprints, "
        "empresas, equipo, planear (necesita text con el objetivo), crear_sprint "
        "(text o sprint_name), despachar, pausar, reanudar, aprobar, rechazar "
        "(run_id y feedback opcional), asignar (text con el encargo y agent con el "
        "nombre), ayuda. Devuelve una frase ya redactada para decir tal cual.",
        "en": "Runs one factory instruction. Valid verbs: estado, sprints, empresas, "
        "equipo, planear (needs text with the goal), crear_sprint (text or "
        "sprint_name), despachar, pausar, reanudar, aprobar, rechazar (run_id and "
        "optional feedback), asignar (text with the task and agent with the name), "
        "ayuda. Returns a sentence already written to be said as is.",
    },
    "build": {
        "es": "Construye al instante un proyecto pequeño a partir de una descripción en "
        "lenguaje natural (página, landing, calculadora, formulario, juego simple) y "
        "devuelve la frase para decir y la URL para abrir.",
        "en": "Builds a small project on the spot from a natural-language description "
        "(page, landing, calculator, form, simple game) and returns the sentence to "
        "say plus the URL to open.",
    },
    "company_id": {
        "es": "Empresa; si se omite, la configurada.",
        "en": "Company; the configured one when omitted.",
    },
    "text": {
        "es": "Objetivo dictado por la persona.",
        "en": "Goal as dictated by the person.",
    },
    "feedback": {"es": "Qué corregir al rechazar.", "en": "What to fix when rejecting."},
    "agent": {
        "es": "A quién se le encarga (nombre o rol), para asignar.",
        "en": "Who gets the task (name or role), for asignar.",
    },
    "build_text": {
        "es": "Qué construir, tal como lo pidió la persona.",
        "en": "What to build, exactly as the person asked for it.",
    },
}


# Actions that decide or start work. The model may ask for them, but they run
# only after the person confirms in their own next phrase: a model can be
# steered by text it reads back (a task title, a feedback note), a person's
# "sí, confirmo" cannot be produced by the model.
CONFIRM_ACTIONS = frozenset({"aprobar", "rechazar", "despachar", "reanudar", "asignar"})
COMMAND_ACTIONS = (
    "estado",
    "empresas",
    "equipo",
    "sprints",
    "planear",
    "crear_sprint",
    "despachar",
    "pausar",
    "reanudar",
    "aprobar",
    "rechazar",
    "asignar",
    "ayuda",
)
_YES = {"si", "si confirmo", "confirmo", "si, confirmo", "yes", "yes confirm", "confirm", "confirmed"}


def is_confirmation(phrase: str) -> bool:
    """True when *phrase* is the person saying yes to the pending action."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", phrase or "").encode("ascii", "ignore").decode()
    plain = " ".join(plain.lower().replace(",", " ").replace(".", " ").replace("!", " ").split())
    return plain in _YES


def confirmation_request(action: str, language: str) -> str:
    if _lang(language) == "en":
        return (
            f"Before I do '{action}' in the factory I need you to confirm it. "
            "Say: yes, confirm. Anything else cancels it."
        )
    return (
        f"Antes de hacer '{action}' en la fábrica necesito que lo confirmes. "
        "Decí: sí, confirmo. Cualquier otra cosa lo cancela."
    )


def register_tools(
    registry: ToolRegistry, client: FactoryClient, language: str = "es"
) -> None:
    """Wire the three factory tools into *registry*, described in *language*.

    Called again when the conversation switches language: the descriptions are
    what steer the model, so an English conversation with Spanish tool text
    drifts back to Spanish.
    """
    language = normalize(language)
    client.language = language

    def factory_status(company_id: int | None = None) -> dict:
        try:
            answer = client.status(company_id)
        except FactoryError as exc:
            return {"ok": False, "speech": str(exc)}
        return {"ok": answer.ok, "speech": answer.speech, "data": answer.data}

    def factory_command(
        action: str,
        text: str | None = None,
        sprint_id: int | None = None,
        run_id: int | None = None,
        sprint_name: str | None = None,
        scope_size: str | None = None,
        feedback: str | None = None,
        agent: str | None = None,
    ) -> dict:
        if action not in COMMAND_ACTIONS:
            return {"ok": False, "speech": f"unknown action: {action}"}
        if action in CONFIRM_ACTIONS:
            client.pending = {
                "action": action,
                "text": text,
                "sprint_id": sprint_id,
                "run_id": run_id,
                "sprint_name": sprint_name,
                "scope_size": scope_size,
                "feedback": feedback,
                "agent": agent,
            }
            return {
                "ok": True,
                "needs_confirmation": True,
                "speech": confirmation_request(action, client.language),
            }
        try:
            answer = client.command(
                action,
                text=text,
                sprint_id=sprint_id,
                run_id=run_id,
                sprint_name=sprint_name,
                scope_size=scope_size,
                feedback=feedback,
                agent=agent,
            )
        except FactoryError as exc:
            return {"ok": False, "speech": str(exc)}
        return {"ok": answer.ok, "speech": answer.speech, "data": answer.data}

    def factory_build(texto: str) -> dict:
        try:
            answer = client.build(texto)
        except FactoryError as exc:
            return {"ok": False, "speech": str(exc), "data": {}}
        return {"ok": answer.ok, "speech": answer.speech, "data": answer.data}

    registry.register(
        "factory_status",
        _description("status", language),
        object_schema(
            {
                "company_id": {
                    "type": "integer",
                    "description": _description("company_id", language),
                }
            }
        ),
        factory_status,
    )

    registry.register(
        "factory_command",
        _description("command", language),
        object_schema(
            {
                "action": {"type": "string", "enum": list(COMMAND_ACTIONS)},
                "text": {"type": "string", "description": _description("text", language)},
                "sprint_id": {"type": "integer"},
                "run_id": {"type": "integer"},
                "sprint_name": {"type": "string"},
                "scope_size": {"type": "string", "enum": ["small", "medium", "large"]},
                "feedback": {
                    "type": "string",
                    "description": _description("feedback", language),
                },
                "agent": {"type": "string", "description": _description("agent", language)},
            },
            required=["action"],
        ),
        factory_command,
        timeout=120.0,
    )

    registry.register(
        "factory_build",
        _description("build", language),
        object_schema(
            {
                "texto": {
                    "type": "string",
                    "description": _description("build_text", language),
                }
            },
            required=["texto"],
        ),
        factory_build,
        timeout=240.0,
    )
