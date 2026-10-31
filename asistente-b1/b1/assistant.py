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
from .sentences import SentenceBuffer
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

        confirmed = await self._settle_pending(phrase)
        if confirmed is not None:
            self._history.append({"role": "user", "content": phrase})
            self._history.append({"role": "assistant", "content": confirmed})
            await self.say(confirmed)
            return confirmed

        self._emit("state", value="thinking")
        self._history.append({"role": "user", "content": phrase})
        voice = _SpokenStream(self) if self._streams() else None
        answer, spoken = await self._converse(voice)
        self._history.append({"role": "assistant", "content": answer})
        if voice is not None:
            await voice.finish(answer if spoken else "")
        if not spoken:
            await self.say(answer)
        return answer

    async def _settle_pending(self, phrase: str) -> str | None:
        """Run or drop the action waiting for the person's confirmation.

        Only the person's own phrase reaches here; the model never does, so it
        cannot confirm an action for them. A yes runs it and returns what the
        factory said; anything else cancels it and the turn goes on as usual.
        """
        factory = self.factory
        pending = getattr(factory, "pending", None) if factory is not None else None
        if not pending:
            return None
        factory.pending = None
        if not fabrica.is_confirmation(phrase):
            self._emit("cancelled", action=pending.get("action"))
            return None
        action = pending.pop("action")
        try:
            answer = await asyncio.to_thread(factory.command, action, **pending)
        except fabrica.FactoryError as exc:
            return str(exc)
        self._after_tool(json.dumps({"ok": answer.ok, "speech": answer.speech, "data": answer.data}))
        return answer.speech

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

    def _streams(self) -> bool:
        """Speak while the model writes, when it can and the settings allow."""
        return bool(getattr(self.settings, "model_stream", True)) and callable(
            getattr(self.model, "stream", None)
        )

    async def _ask(self, messages, tools, voice: "_SpokenStream | None") -> Reply:
        """One model turn; with a voice, each finished sentence is spoken at once."""
        if voice is None:
            return await asyncio.to_thread(self.model.complete, messages, tools)
        buffer = SentenceBuffer()
        loop = asyncio.get_running_loop()

        def on_text(piece: str) -> None:
            # Runs on the model's thread; the voice lives on the event loop.
            for sentence in buffer.feed(piece):
                loop.call_soon_threadsafe(voice.put, sentence)

        voice.new_round()
        try:
            reply = await asyncio.to_thread(self.model.stream, messages, tools, on_text)
        finally:
            # Sentences queued from the thread run before this point; the rest
            # of the text follows them.
            await asyncio.sleep(0)
            for sentence in buffer.flush():
                voice.put(sentence)
        return reply

    async def _converse(self, voice: "_SpokenStream | None" = None) -> tuple[str, bool]:
        """The answer to the turn, and whether the voice already said it."""
        if self.model is None:
            return t(self.language, "assistant.no_key"), False

        messages = self._messages()
        tools = self.registry.declarations()
        for round_index in range(MAX_TOOL_ROUNDS):
            try:
                reply = await self._ask(messages, tools, voice)
            except ModelError as exc:
                self._emit("error", message=str(exc))
                return self._model_failure(str(exc)), False

            if not reply.wants_tools:
                answer = self._clean(reply.text)
                if answer and voice is not None and voice.said_this_round():
                    return answer, True
                return answer or self._empty_reply(), False

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

        return t(self.language, "assistant.loop_limit"), False

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
        if url and not self._is_factory_preview(str(url)):
            self._emit("error", message=f"no abro un enlace fuera de la fábrica: {url}")
            url = None
        if url and body.get("ok") and self.settings.open_build_in_browser:
            try:
                webbrowser.open(str(url), new=2)
                self._emit("opened", url=str(url))
            except Exception as exc:  # noqa: BLE001 - say it, do not crash.
                self._emit("error", message=f"no pude abrir {url}: {exc}")

    def _is_factory_preview(self, url: str) -> bool:
        """Only the factory's own build previews are opened, over http(s)."""
        if self.factory is None:
            return False
        prefix = self.factory.base_url.rstrip("/") + "/v1/voice/build/"
        return url.startswith(prefix) and url.split(":", 1)[0] in {"http", "https"}

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


class _SpokenStream:
    """Says the sentences of a streamed answer in order, as they come.

    The speaker runs in its own task, so the model keeps writing while the
    first sentence is being said. The interface sees every sentence once
    (``reply_part``) and the whole answer at the end (``reply`` with
    ``streamed``), so it can grow the answer instead of repeating it.
    """

    def __init__(self, assistant: Assistant) -> None:
        self.assistant = assistant
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.parts: list[str] = []
        self._round_start = 0

    def new_round(self) -> None:
        self._round_start = len(self.parts)

    def said_this_round(self) -> bool:
        return len(self.parts) > self._round_start

    def put(self, sentence: str) -> None:
        clean = self.assistant._clean(sentence)
        if not clean:
            return
        assistant = self.assistant
        if self.task is None:
            try:
                assistant.speaker.language = assistant.language
            except Exception:  # noqa: BLE001 - a custom speaker may be read-only
                pass
            assistant._emit("state", value="speaking")
            self.task = asyncio.get_running_loop().create_task(self._speak())
        self.parts.append(clean)
        assistant._emit("reply_part", text=clean)
        self.queue.put_nowait(clean)

    async def _speak(self) -> None:
        while True:
            sentence = await self.queue.get()
            if sentence is None:
                return
            try:
                await asyncio.to_thread(self.assistant.speaker.say, sentence)
            except Exception as exc:  # noqa: BLE001 - one bad sentence, not the turn
                self.assistant._emit("error", message=str(exc))

    async def finish(self, answer: str) -> None:
        """Wait until everything queued has been said."""
        if self.task is None:
            return
        self.queue.put_nowait(None)
        try:
            await self.task
        finally:
            if answer:
                self.assistant._emit("reply", text=answer, streamed=True)
            self.assistant._emit("state", value="idle")


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
