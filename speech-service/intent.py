"""The understanding tier a model provides: free speech to one of the
application's actions.

The client sends what was heard and the catalogue of what it can do (ids,
labels, the items an action takes); the model picks one, or none. It is
asked for a fixed JSON answer a parser checks, the way the desktop
assistant and the ScrumMaster are: an answer outside the catalogue is no
answer, and the client falls back to its grammar's "I did not catch that".
The model never runs anything; the client still confirms what matters.

Any OpenAI-compatible chat endpoint serves (the factory's LLM proxy,
Nebius, a local server): ``SPEECH_LLM_URL``, ``SPEECH_LLM_KEY``,
``SPEECH_LLM_MODEL``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

BUILTINS = ("yes", "no", "help")
MAX_ACTIONS = 60
MAX_ITEMS = 60


@dataclass
class ActionDescription:
    id: str
    label: str
    description: str = ""
    items: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Intent:
    intent: str | None
    item: str | None = None
    reply: str | None = None


class IntentResolver(Protocol):
    def resolve(self, transcript: str, lang: str, actions: list[ActionDescription], context: str) -> Intent: ...

    def describe(self) -> dict: ...


_SYSTEM = {
    "es": (
        "Sos el intérprete de voz de una aplicación. La persona habló; te doy la "
        "transcripción y la lista de acciones que la aplicación sabe hacer. Elegí "
        "la acción que la persona pidió, o ninguna si no pidió ninguna de la lista. "
        "Si la acción lleva un elemento, elegí el elemento por su nombre o su "
        "posición (\"la segunda\"). \"sí\" y \"no\" son respuestas a una pregunta "
        "anterior; \"help\" es pedir qué se puede decir.\n"
        "Respondé solo con JSON, sin texto alrededor, con esta forma exacta:\n"
        '{"intent": "<id de acción, yes, no, help o null>", "item": "<id de elemento o null>", '
        '"reply": "<una frase corta para decirle a la persona, o null>"}\n'
        "No inventes acciones ni elementos que no estén en la lista. Si dudás, "
        "intent null y una reply que pregunte qué quiso decir, en una frase."
    ),
    "en": (
        "You are the voice interpreter of an application. The person spoke; you get "
        "the transcript and the list of actions the application can do. Pick the "
        "action the person asked for, or none if they asked for nothing on the list. "
        "If the action takes an item, pick the item by its name or its place (\"the "
        "second one\"). \"yes\" and \"no\" answer an earlier question; \"help\" asks what "
        "can be said.\n"
        "Answer with JSON only, nothing around it, in exactly this shape:\n"
        '{"intent": "<an action id, yes, no, help or null>", "item": "<an item id or null>", '
        '"reply": "<one short sentence to say to the person, or null>"}\n'
        "Never invent actions or items that are not on the list. If in doubt, "
        "intent null and a one-sentence reply asking what they meant."
    ),
}


def catalogue_text(actions: list[ActionDescription], lang: str) -> str:
    lines = []
    for a in actions[:MAX_ACTIONS]:
        line = f"- {a.id}: {a.label}"
        if a.description:
            line += f" — {a.description}"
        if a.items:
            items = ", ".join(f"{i.get('id')} ({i.get('label', '')})" for i in a.items[:MAX_ITEMS])
            line += (" · elementos: " if lang == "es" else " · items: ") + items
        lines.append(line)
    return "\n".join(lines)


def parse_answer(text: str, actions: list[ActionDescription]) -> Intent:
    """The model's JSON, checked against the catalogue; anything else is no answer."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return Intent(None)
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return Intent(None)
    if not isinstance(data, dict):
        return Intent(None)
    intent = data.get("intent")
    item = data.get("item")
    reply = data.get("reply")
    allowed = {a.id: a for a in actions}
    if intent not in allowed and intent not in BUILTINS:
        intent = None
    if intent in allowed and item is not None:
        if not any(i.get("id") == item for i in allowed[intent].items):
            item = None
    else:
        item = None
    reply = reply.strip()[:300] if isinstance(reply, str) and reply.strip() else None
    return Intent(intent, item, reply)


Post = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _urllib_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the address is the operator's
        return json.loads(response.read().decode("utf-8"))


class LlmIntentResolver:
    """An OpenAI-compatible chat endpoint, asked for JSON and read strictly."""

    def __init__(self, url: str, model: str, api_key: str = "", *, post: Post = _urllib_post, temperature: float = 0.0) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.post = post
        self.temperature = temperature

    def configured(self) -> bool:
        return bool(self.url and self.model)

    def resolve(self, transcript: str, lang: str, actions: list[ActionDescription], context: str = "") -> Intent:
        if not self.configured():
            raise RuntimeError("no model configured")
        lang = "es" if lang == "es" else "en"
        user = (
            (f"Contexto: {context}\n" if context and lang == "es" else f"Context: {context}\n" if context else "")
            + ("Acciones:\n" if lang == "es" else "Actions:\n")
            + catalogue_text(actions, lang)
            + ("\n\nLa persona dijo: " if lang == "es" else "\n\nThe person said: ")
            + f"«{transcript.strip()}»"
        )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": 200,
            "messages": [{"role": "system", "content": _SYSTEM[lang]}, {"role": "user", "content": user}],
        }
        try:
            body = self.post(f"{self.url}/chat/completions", headers, payload)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"model unreachable: {exc}") from None
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return Intent(None)
        return parse_answer(text or "", actions)

    def describe(self) -> dict:
        return {"engine": "openai-compatible", "model": self.model, "configured": self.configured()}
