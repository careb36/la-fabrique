"""The conversation loop: history, model turn, tool turn, spoken answer.

Deliberately small. The assistant owns three decisions and delegates the rest:
which language this turn is in, when to stop calling tools, and what to hand to
the speaker. Everything the model can *do* lives in the tool registry.
"""

from __future__ import annotations

import asyncio
import json
import webbrowser
from collections import deque
from typing import Any, Callable

from . import fabrica
from .config import Settings
from .i18n import normalize, t
from .llm import ChatModel, ModelError, Reply
from .prompts import system_prompt
from .speech import Silence
from .tools import ToolRegistry

MAX_TOOL_ROUNDS = 5
HISTORY_TURNS = 12

SPANISH_HINTS = {
    "que", "qué", "como", "cómo", "donde", "dónde", "para", "porque", "pero",
    "esta", "está", "esto", "hace", "hacé", "armá", "quiero", "necesito", "podes",
    "podés", "decime", "dale", "buenas", "gracias", "sprint", "estado", "fábrica",
}
ENGLISH_HINTS = {
    "the", "what", "how", "please", "thanks", "build", "make", "status", "could",
    "would", "there", "about", "with", "this", "that", "want", "need",
}


def detect_language(text: str, default: str = "es", *, hint: str = "") -> str:
    """Guess the language of one phrase by stop-word count.

    Cheap on purpose: it only has to be right about the two languages the
    assistant is configured for, and a wrong guess costs one clarifying turn.
    ``hint`` (what the transcriber heard) only breaks ties, because a pinned
    listening language says nothing about the words that came in.
    """
    words = [w.strip("¿?¡!.,;:«»\"“”").lower() for w in (text or "").split()]
    spanish = sum(1 for w in words if w in SPANISH_HINTS)
    english = sum(1 for w in words if w in ENGLISH_HINTS)
    if spanish == english:
        if hint and hint.startswith(("es", "en")):
            return hint[:2]
        return normalize(default)
    return "es" if spanish > english else "en"


class Assistant:
    """Ties model, tools, factory and voice into one turn-taking object."""

    def __init__(
        self,
        settings: Settings,
        model: ChatModel | None,
        registry: ToolRegistry,
        *,
        factory: fabrica.FactoryClient | None = None,
        speaker: Any | None = None,
        on_event: Callable[[dict], None] | None = None,
        history_turns: int = HISTORY_TURNS,
        retranslate_tools: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.registry = registry
        self.factory = factory
        self.speaker = speaker or Silence()
        self.on_event = on_event
        self._retranslate_tools = retranslate_tools
        self.language = normalize(settings.language)
        self._history: deque[dict[str, Any]] = deque(maxlen=history_turns * 2)
        self._started = False

    # -- events -------------------------------------------------------------
    def _emit(self, kind: str, **payload: Any) -> None:
        if not self.on_event:
            return
        try:
            self.on_event({"type": kind, **payload})
        except Exception:  # noqa: BLE001 - a broken UI must not break the turn.
            pass

    # -- startup ------------------------------------------------------------
    async def startup(self) -> dict[str, str]:
        """Show the factory guide and say the short version of it.

        Fixed text on both sides: the panel and the voice cannot drift, and it
        costs no model call — so it still works with no API key loaded.
        """
        title = fabrica.guide_title(self.language)
        body = fabrica.guide_text(self.language)
        summary = fabrica.spoken_summary(self.language)
        self._emit("guide", title=title, text=body)
        self._started = True
        if self.settings.briefing:
            await self.say(summary)
        return {"title": title, "text": body, "spoken": summary}

    async def say(self, text: str) -> None:
        if not text:
            return
        # The engine reads the text exactly when it is spoken, so a voice per
        # language is decided here and not when the speaker was built.
        try:
            self.speaker.language = self.language
        except Exception:  # noqa: BLE001 - a custom speaker may be read-only
            pass
        self._emit("state", value="speaking")
        self._emit("reply", text=text)
        try:
            await asyncio.to_thread(self.speaker.say, text)
        finally:
            self._emit("state", value="idle")

    # -- one turn -----------------------------------------------------------
    async def handle(self, text: str, language: str | None = None) -> str:
        """Answer one user phrase, calling tools as needed, and speak it."""
        phrase = " ".join((text or "").split())
        if not phrase:
            return ""
        hint = normalize(language) if (language or "").strip() else ""
        self.set_language(detect_language(phrase, self.language, hint=hint))

        self._emit("state", value="thinking")
        self._history.append({"role": "user", "content": phrase})
        answer = await self._converse()
        self._history.append({"role": "assistant", "content": answer})
        await self.say(answer)
        return answer

    def set_language(self, code: str) -> None:
        """Switch the whole assistant: prompt, tool text, factory and voice.

        The person can change language mid-conversation, and every layer has to
        follow in the same turn or the next answer comes out half translated.
        """
        wanted = normalize(code)
        if wanted == self.language:
            return
        self.language = wanted
        if self.factory is not None:
            self.factory.language = wanted
        if self._retranslate_tools is not None:
            try:
                self._retranslate_tools(wanted)
            except Exception:  # noqa: BLE001 - the conversation goes on regardless
                pass
        try:
            self.speaker.language = wanted
        except Exception:  # noqa: BLE001
            pass
        self._emit("language", value=wanted)

    async def _converse(self) -> str:
        if self.model is None:
            return t(self.language, "assistant.no_key")

        messages = self._messages()
        tools = self.registry.declarations()
        for round_index in range(MAX_TOOL_ROUNDS):
            try:
                reply = await asyncio.to_thread(self.model.complete, messages, tools)
            except ModelError as exc:
                self._emit("error", message=str(exc))
                return self._model_failure(str(exc))

            if not reply.wants_tools:
                return self._clean(reply.text) or self._empty_reply()

            messages.append(_assistant_message(reply))
            for call in reply.tool_calls:
                result = await self.registry.dispatch(call.name, call.arguments)
                self._emit("tool", name=call.name, result=result)
                self._after_tool(result)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
            if round_index == MAX_TOOL_ROUNDS - 1:
                break

        return t(self.language, "assistant.loop_limit")

    # -- helpers ------------------------------------------------------------
    def _messages(self) -> list[dict[str, Any]]:
        system = system_prompt(self.settings, self.registry.names(), self.language)
        return [{"role": "system", "content": system}, *self._history]

    def _after_tool(self, raw: str) -> None:
        """Open the built project and let the UI mirror the factory numbers."""
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(body, dict):
            return
        data = body.get("data") or {}
        self._emit("factory", ok=bool(body.get("ok")), data=data)
        url = data.get("url") if isinstance(data, dict) else None
        if url and body.get("ok") and self.settings.open_build_in_browser:
            try:
                webbrowser.open(str(url), new=2)
                self._emit("opened", url=str(url))
            except Exception as exc:  # noqa: BLE001 - say it, do not crash.
                self._emit("error", message=f"no pude abrir {url}: {exc}")

    def _clean(self, text: str) -> str:
        """Drop formatting that sounds wrong once it is read aloud."""
        clean = " ".join((text or "").split())
        for token in ("**", "__", "`", "#"):
            clean = clean.replace(token, "")
        return clean.strip()

    def _empty_reply(self) -> str:
        return t(self.language, "assistant.done")

    def _model_failure(self, detail: str) -> str:
        return t(self.language, "assistant.model_failure", detail=detail)

    def reset(self) -> None:
        self._history.clear()
        self._emit("state", value="idle")


def _assistant_message(reply: Reply) -> dict[str, Any]:
    """The assistant turn in the shape the tools protocol expects back."""
    return {
        "role": "assistant",
        "content": reply.text or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in reply.tool_calls
        ],
    }


def build_assistant(settings: Settings, *, on_event=None) -> Assistant:
    """Wire a ready assistant from settings, degrading what is not installed."""
    from .llm import model_from_settings

    registry = ToolRegistry()
    factory = None
    retranslate = None
    if settings.factory_url:
        factory = fabrica.FactoryClient(
            settings.factory_url_clean(),
            settings.voice_key,
            company_id=settings.factory_company_id,
            language=settings.language,
        )
        fabrica.register_tools(registry, factory, settings.language)
        retranslate = lambda code: fabrica.register_tools(registry, factory, code)  # noqa: E731

    model = None
    if not settings.missing():
        model = model_from_settings(settings)
    return Assistant(
        settings,
        model,
        registry,
        factory=factory,
        on_event=on_event,
        retranslate_tools=retranslate,
    )
