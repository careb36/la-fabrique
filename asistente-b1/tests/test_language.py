"""Spanish and English, everywhere a person can read or hear them.

The dictionary is the contract: if a key exists in one language it exists in
the other, and the assistant switches prompt, tools, factory and voice in the
same turn it switches language.
"""

from __future__ import annotations

import json

import pytest

from b1 import i18n
from b1.assistant import Assistant, build_assistant, detect_language
from b1.config import Settings
from b1.prompts import system_prompt
from b1.tools import ToolRegistry


class _Recorder:
    """A speaker that only remembers what it was asked to say and in which language."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []
        self.language = "es"

    def say(self, text: str) -> None:
        self.said.append((self.language, text))

    def stop(self) -> None:
        return None


def test_every_text_exists_in_both_languages():
    for key in i18n.keys():
        for language in i18n.LANGUAGES:
            text = i18n.t(language, key)
            assert text.strip(), f"{key} está vacío en {language}"
            assert isinstance(text, str)


def test_unknown_language_falls_back_to_spanish():
    assert i18n.t("fr", "ui.talk") == i18n.t("es", "ui.talk")
    assert i18n.t(None, "ui.talk") == i18n.t("es", "ui.talk")


def test_placeholders_are_filled():
    assert "42" in i18n.t("es", "dev.described", label="mic", name="USB", index=42)
    assert "USB" in i18n.t("en", "dev.described", label="mic", name="USB", index=1)


def test_an_unknown_key_fails_loudly():
    with pytest.raises(KeyError):
        i18n.t("es", "no.existe")


def test_normalize_accepts_prefixes_and_case():
    assert i18n.normalize("EN") == "en"
    assert i18n.normalize("english") == "en"  # a prefix is enough
    assert i18n.normalize("es-AR") == "es"
    assert i18n.normalize("") == "es"


def test_the_prompt_is_written_in_the_session_language():
    settings = Settings(language="es")
    spanish = system_prompt(settings, ["factory_status"], "es")
    english = system_prompt(settings, ["factory_status"], "en")

    assert "LA FÁBRICA" in spanish and "factory_status" in spanish
    assert "THE FACTORY" in english and "factory_status" in english
    assert "THE FACTORY" not in spanish


def test_detection_uses_the_hint_only_to_break_ties():
    assert detect_language("¿cómo va la fábrica?", "es") == "es"
    assert detect_language("how is the factory doing?", "es") == "en"
    # "ok" carries no evidence: the transcriber's guess decides.
    assert detect_language("ok", "es", hint="en") == "en"
    assert detect_language("ok", "es", hint="") == "es"
    assert detect_language("ok", "en", hint="") == "en"


def test_switching_language_moves_prompt_tools_voice_and_factory():
    settings = Settings(language="es", factory_url="http://127.0.0.1:1")
    registry = ToolRegistry()

    def retranslate(code: str) -> None:
        registry.register("factory_status", f"status in {code}", {"type": "object"}, lambda: {})

    retranslate("es")
    factory = _StubFactory()
    assistant = Assistant(
        settings, None, registry, factory=factory, retranslate_tools=retranslate
    )
    assistant.speaker = _Recorder()
    events: list[dict] = []
    assistant.on_event = events.append

    assistant.set_language("en")

    assert assistant.language == "en"
    assert assistant.speaker.language == "en"
    assert factory.language == "en"
    assert registry.get("factory_status").description == "status in en"
    assert {"type": "language", "value": "en"} in events


def test_the_answer_language_follows_the_phrase_not_the_settings():
    settings = Settings(language="es")
    assistant = Assistant(settings, None, ToolRegistry())
    assistant.speaker = _Recorder()

    import asyncio

    asyncio.run(assistant.handle("what is the status of the factory?"))
    assert assistant.language == "en"
    assert assistant.speaker.language == "en"

    asyncio.run(assistant.handle("¿y cómo va la fábrica?"))
    assert assistant.language == "es"


def test_a_missing_model_speaks_the_right_language():
    import asyncio

    for language in ("es", "en"):
        assistant = Assistant(Settings(language=language), None, ToolRegistry())
        assistant.speaker = _Recorder()
        answer = asyncio.run(assistant.handle("hola" if language == "es" else "hello"))
        assert answer == i18n.t(language, "assistant.no_key")


def test_build_assistant_wires_the_factory_tools_in_the_saved_language(tmp_path, monkeypatch):
    monkeypatch.setenv("B1_HOME", str(tmp_path))
    settings = Settings(language="en", factory_url="http://127.0.0.1:1")
    assistant = build_assistant(settings)
    description = assistant.registry.get("factory_status").description
    assert description.startswith("Factory status")


def test_settings_save_and_load_keep_the_language_choices(tmp_path):
    settings = Settings(language="en", stt_language="es", tts_voice_en="/tmp/en.onnx")
    path = settings.save(tmp_path / "config.json")
    loaded = Settings.load(path)
    assert loaded.language == "en"
    assert loaded.stt_language == "es"
    assert loaded.tts_voice_en == "/tmp/en.onnx"


def test_an_unknown_listening_language_becomes_automatic(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"stt_language": "klingon"}), "utf-8")
    assert Settings.load(tmp_path / "config.json").stt_language == "auto"


def test_speech_language_respects_a_pinned_value():
    automatic = Settings(language="es", stt_language="auto")
    assert automatic.speech_language() == "es"
    assert automatic.speech_language("en") == "en"

    pinned = Settings(language="en", stt_language="es")
    assert pinned.speech_language() == "es"
    assert pinned.speech_language("en") == "es"


class _StubFactory:
    def __init__(self) -> None:
        self.language = "es"


def test_both_guides_exist_and_differ():
    from b1.fabrica import guide_text, guide_title, spoken_summary

    for function in (guide_text, guide_title, spoken_summary):
        spanish, english = function("es"), function("en")
        assert spanish and english and spanish != english


def test_the_help_is_written_in_the_language_asked_for(capsys):
    from b1.app import main

    for language, own, other in (
        ("es", "descargar las voces", "download the configured"),
        ("en", "download the configured", "descargar las voces"),
    ):
        with pytest.raises(SystemExit):
            main(["--help", "--language", language])
        out = capsys.readouterr().out
        assert own in out and other not in out


def test_voices_explains_when_the_settings_are_already_paths(tmp_path, monkeypatch, capsys):
    from b1.app import main

    model = tmp_path / "voz.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("B1_HOME", str(tmp_path))
    monkeypatch.setenv("B1_TTS_VOICE", str(model))
    monkeypatch.setenv("B1_TTS_VOICE_EN", str(model))

    assert main(["--voices", "--language", "en"]) == 0
    assert "nothing to download" in capsys.readouterr().out


def test_voices_downloads_names_and_says_where_they_land(tmp_path, monkeypatch, capsys):
    from b1 import app as app_module

    monkeypatch.setenv("B1_HOME", str(tmp_path))
    monkeypatch.delenv("B1_TTS_VOICE", raising=False)
    monkeypatch.delenv("B1_TTS_VOICE_EN", raising=False)
    monkeypatch.setattr(
        app_module, "download_voices", lambda names: {name: "" for name in names}
    )

    assert app_module.main(["--voices"]) == 0
    out = capsys.readouterr().out
    assert "es_ES-sharvard-medium" in out and "en_US-amy-medium" in out
    assert str(tmp_path) in out
