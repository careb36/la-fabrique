"""The speaking side of the voice: which engine wins and what it is told.

No machine here has SAPI, ``say`` or ``espeak``, and none of that matters: the
command each engine would run is a value we can read, in both languages, with
the text properly escaped.
"""

from __future__ import annotations

import base64
import subprocess

import pytest

from b1 import speech
from b1.speech import (
    ConsoleSpeaker,
    PiperSpeaker,
    SystemSpeaker,
    describe_voice,
    make_speaker,
    system_voice_ready,
)


class _Runner:
    """Records what would have been executed."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        return subprocess.CompletedProcess(
            command, self.returncode, stdout=self.stdout, stderr=self.stderr
        )


def _decoded(argument: str) -> str:
    return base64.b64decode(argument.encode("ascii")).decode("utf-16-le")


def test_windows_speaks_through_an_encoded_script():
    speaker = SystemSpeaker("sapi", language="es")
    command = speaker.command("Hola, ¿cómo va la fábrica?")

    assert command[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    script = _decoded(command[-1])
    assert "Hola, ¿cómo va la fábrica?" in script
    assert "$want = 'es'" in script


def test_windows_picks_the_english_voice_when_the_answer_is_english():
    speaker = SystemSpeaker("sapi", language="en")
    script = _decoded(speaker.command("All good.")[-1])
    assert "$want = 'en'" in script


def test_apostrophes_survive_the_powershell_string():
    speaker = SystemSpeaker("sapi")
    script = _decoded(speaker.command("It's done")[-1])
    assert "$engine.Speak('It''s done');" in script


def test_macos_uses_the_voice_for_the_language():
    speaker = SystemSpeaker(
        "say", voices={"es": "Mónica", "en": "Samantha"}, language="en"
    )
    assert speaker.command("Hello") == ["say", "-v", "Samantha", "Hello"]
    speaker.language = "es"
    assert speaker.command("Hola") == ["say", "-v", "Mónica", "Hola"]


def test_macos_without_a_matching_voice_still_speaks():
    speaker = SystemSpeaker("say", voices={}, language="es")
    assert speaker.command("Hola") == ["say", "Hola"]


def test_linux_says_the_language_twice_where_it_matters():
    assert SystemSpeaker("spd-say", language="en").command("Hi") == [
        "spd-say",
        "-w",
        "-l",
        "en",
        "Hi",
    ]
    assert SystemSpeaker("espeak-ng", language="es").command("Hola") == [
        "espeak-ng",
        "-v",
        "es",
        "Hola",
    ]


def test_an_empty_sentence_asks_for_nothing():
    assert SystemSpeaker("say").command("   ") == []


def test_speaking_calls_the_engine_and_never_raises():
    runner = _Runner()
    SystemSpeaker("say", runner=runner, language="en").say("Ready.")
    assert runner.calls == [["say", "Ready."]]


def test_a_broken_engine_falls_back_to_the_console(capsys):
    def exploding(command, **kwargs):
        raise OSError("no hay motor")

    SystemSpeaker("say", runner=exploding, language="en").say("Still here.")
    assert "Still here." in capsys.readouterr().out


def test_macos_voice_list_is_parsed_by_language():
    listing = (
        "Samantha            en_US    # Hello, my name is Samantha.\n"
        "Mónica              es_ES    # Hola, me llamo Mónica.\n"
        "Paulina             es_MX    # Hola, me llamo Paulina.\n"
    )
    voices = SystemSpeaker._say_voices(_Runner(listing))
    assert voices["en"] == "Samantha"
    assert voices["es"] == "Mónica"


def test_detection_prefers_piper_then_the_system_then_the_console(tmp_path, monkeypatch):
    model = tmp_path / "es.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setattr(speech.shutil, "which", lambda name: "/usr/bin/piper")

    speaker = make_speaker(str(model), language="es")
    assert isinstance(speaker, PiperSpeaker)

    monkeypatch.setattr(speech.shutil, "which", lambda name: None)
    monkeypatch.setattr(SystemSpeaker, "detect", classmethod(lambda cls, **kw: SystemSpeaker("say")))
    assert isinstance(make_speaker(str(model), language="es"), SystemSpeaker)

    monkeypatch.setattr(SystemSpeaker, "detect", classmethod(lambda cls, **kw: None))
    fallback = make_speaker(str(model), language="en")
    assert isinstance(fallback, ConsoleSpeaker)
    assert fallback.language == "en"


def test_piper_picks_the_model_of_the_language_being_spoken(tmp_path):
    spanish, english = tmp_path / "es.onnx", tmp_path / "en.onnx"
    for path in (spanish, english):
        path.write_bytes(b"onnx")
    speaker = PiperSpeaker({"es": spanish, "en": english}, language="es")

    assert speaker.model_for() == spanish
    speaker.language = "en"
    assert speaker.model_for() == english
    # A language without a model borrows the one that exists instead of going mute.
    speaker.language = "fr"
    assert speaker.model_for() in {spanish, english}


def test_make_speaker_ignores_a_voice_file_that_is_not_there(tmp_path, monkeypatch):
    monkeypatch.setattr(speech.shutil, "which", lambda name: "/usr/bin/piper")
    monkeypatch.setattr(SystemSpeaker, "detect", classmethod(lambda cls, **kw: None))
    assert isinstance(make_speaker(str(tmp_path / "falta.onnx")), ConsoleSpeaker)


def test_describe_voice_names_the_engine_in_both_languages(tmp_path, monkeypatch):
    model = tmp_path / "es_ES-sharvard-medium.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setattr(speech.shutil, "which", lambda name: "/usr/bin/piper")
    _speaker, spanish = describe_voice(str(model), language="es")
    assert "Piper" in spanish
    assert model.name in spanish

    _speaker, english = describe_voice("", language="en")
    assert "Piper" in english or "voice" in english.lower()


def test_system_voice_ready_matches_detection(monkeypatch):
    monkeypatch.setattr(SystemSpeaker, "detect", classmethod(lambda cls, **kw: None))
    assert system_voice_ready() is False
    monkeypatch.setattr(
        SystemSpeaker, "detect", classmethod(lambda cls, **kw: SystemSpeaker("say"))
    )
    assert system_voice_ready() is True


def test_an_engine_that_fails_falls_back_to_text_once(capsys):
    runner = _Runner(returncode=3, stderr="boom")
    speaker = SystemSpeaker("say", runner=runner, language="es")

    speaker.say("Primera.")
    speaker.say("Segunda.")

    out = capsys.readouterr()
    assert "Primera." in out.out and "Segunda." in out.out
    assert out.err.count("no pudo sonar") == 1


def test_espeak_silently_muted_still_reaches_the_person(capsys):
    # espeak-ng exits 0 while printing this, so the status code is not enough.
    runner = _Runner(stderr="ALSA lib conf.c:5205: error\nerror: No such file or directory\n")
    speaker = SystemSpeaker("espeak-ng", runner=runner, language="en")

    speaker.say("Still here.")

    out = capsys.readouterr()
    assert "Still here." in out.out
    assert "No such file or directory" in out.err


def test_a_clean_run_prints_nothing_extra(capsys):
    speaker = SystemSpeaker("say", runner=_Runner(), language="en")
    speaker.say("Perfect.")
    assert capsys.readouterr().err == ""


def test_a_bare_setting_is_a_voice_name_and_a_file_is_a_path(tmp_path):
    model = tmp_path / "voz.onnx"
    model.write_bytes(b"onnx")

    assert speech.voice_name("es_ES-sharvard-medium") == "es_ES-sharvard-medium"
    assert speech.voice_name(str(model)) == ""
    assert speech.voice_name("modelo.onnx") == ""
    assert speech.voice_name("") == ""
    assert speech.voice_name(None) == ""


def test_a_downloaded_voice_is_found_by_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, "voices_dir", lambda: tmp_path)
    monkeypatch.setattr(speech.shutil, "which", lambda name: "/usr/bin/piper")
    (tmp_path / "es_ES-sharvard-medium.onnx").write_bytes(b"onnx")

    speaker = speech.PiperSpeaker("es_ES-sharvard-medium", language="es")

    assert speaker.model_for() == tmp_path / "es_ES-sharvard-medium.onnx"


def test_download_skips_voices_that_are_already_there(tmp_path):
    (tmp_path / "voz.onnx").write_bytes(b"onnx")
    runner = _Runner()

    assert speech.download_voices(["voz"], tmp_path, runner=runner) == {"voz": ""}
    assert runner.calls == []


def test_download_uses_the_interpreter_that_owns_piper(tmp_path, monkeypatch):
    attempts: list[str] = []

    def runner(command, **kwargs):
        attempts.append(command[0])
        if "tiene-piper" in command[0]:
            (tmp_path / f"{command[-1]}.onnx").write_bytes(b"onnx")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "No module named piper")

    monkeypatch.setattr(speech, "_python_candidates", lambda: ["/sin/piper", "/hay/tiene-piper/python"])
    assert speech.download_voices(["voz"], tmp_path, runner=runner) == {"voz": ""}
    assert attempts == ["/sin/piper", "/hay/tiene-piper/python"]


def test_download_reports_why_it_could_not(tmp_path, monkeypatch):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "No module named piper\n")

    monkeypatch.setattr(speech, "_python_candidates", lambda: ["/uno"])
    result = speech.download_voices(["voz"], tmp_path, runner=runner)
    assert "No module named piper" in result["voz"]
