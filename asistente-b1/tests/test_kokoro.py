"""Kokoro first, then Piper, the system voice and the console."""

from __future__ import annotations

import hashlib
import io
import os
import wave
from pathlib import Path

import pytest

from b1 import kokoro, speech
from b1.config import Settings
from b1.speech import ConsoleSpeaker, make_speaker


class FakeKokoro:
    name = "kokoro"

    def __init__(self, language="es"):
        self.language = language

    def voice_for(self, language=None):
        return {"es": "ef_dora", "en": "af_heart"}[language or self.language]

    def say(self, text):
        pass

    def stop(self):
        pass


# -- which speaker ------------------------------------------------------------
def test_kokoro_leads_the_chain_and_the_engine_setting_skips_it(monkeypatch):
    monkeypatch.setattr(kokoro.KokoroSpeaker, "if_available", classmethod(lambda cls, **kw: FakeKokoro()))
    assert isinstance(make_speaker(), FakeKokoro)
    assert isinstance(make_speaker(engine="kokoro"), FakeKokoro)
    monkeypatch.setattr(speech.SystemSpeaker, "if_available", classmethod(lambda cls, **kw: None))
    assert isinstance(make_speaker(engine="piper"), ConsoleSpeaker)  # no Piper here either
    assert isinstance(make_speaker(engine="system"), ConsoleSpeaker)


def test_without_its_files_kokoro_is_not_offered(tmp_path, monkeypatch):
    monkeypatch.setenv("B1_KOKORO_DIR", str(tmp_path))
    assert kokoro.KokoroSpeaker.if_available() is None


def test_the_settings_choose_engine_and_voices(monkeypatch):
    monkeypatch.setenv("B1_TTS_ENGINE", "Piper")
    monkeypatch.setenv("B1_KOKORO_VOICE", "em_alex")
    settings = Settings().apply_env()
    assert settings.tts_engine == "piper"
    assert settings.kokoro_voice == "em_alex"
    monkeypatch.setenv("B1_TTS_ENGINE", "loud")
    assert Settings().apply_env().tts_engine == "auto"

    seen = {}

    def fake(cls, **kw):
        seen.update(kw)
        return FakeKokoro()

    monkeypatch.setattr(kokoro.KokoroSpeaker, "if_available", classmethod(fake))
    monkeypatch.delenv("B1_TTS_ENGINE")
    speaker, line = speech.describe_voice(language="en", settings=Settings().apply_env())
    assert isinstance(speaker, FakeKokoro)
    assert seen["voice"] == "em_alex" and seen["voice_en"] == "af_heart"
    assert line == "Kokoro (af_heart)"


def test_a_voice_per_language_and_the_defaults_fill_the_gaps(tmp_path):
    speaker = kokoro.KokoroSpeaker(tmp_path, voices={"es": "em_alex", "en": ""})
    assert speaker.voice_for("es") == "em_alex"
    assert speaker.voice_for("en") == "af_heart"
    speaker.language = "en"
    assert speaker.voice_for() == "af_heart"


# -- saying it, and falling back ----------------------------------------------
def test_a_failing_engine_still_gets_the_words_out(tmp_path, monkeypatch, capsys):
    speaker = kokoro.KokoroSpeaker(tmp_path)
    monkeypatch.setattr(speaker, "synthesize", lambda text: (_ for _ in ()).throw(RuntimeError("x")))
    speaker.say("La fábrica está al día.")
    assert "La fábrica está al día." in capsys.readouterr().out


def test_without_a_device_the_audio_is_handed_over_as_a_wav(tmp_path, monkeypatch, capsys):
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(kokoro.tempfile, "gettempdir", lambda: str(tmp_path))
    speaker = kokoro.KokoroSpeaker(tmp_path)
    monkeypatch.setattr(speaker, "synthesize", lambda text: (np.full(2400, 0.5, "float32"), 24_000))

    def no_device(samples, rate):
        raise OSError("no output device")

    monkeypatch.setattr(speaker, "_play", no_device)
    speaker.say("hola")
    wav = tmp_path / "b1-voz.wav"
    assert str(wav) in capsys.readouterr().out
    with wave.open(str(wav)) as handle:
        assert handle.getframerate() == 24_000 and handle.getnframes() == 2400


# -- the download is checked before it is used --------------------------------
def _serving(contents: dict[str, bytes]):
    def opener(url, timeout=0):
        return io.BytesIO(contents[url.rsplit("/", 1)[1]])

    return opener


def test_files_are_kept_only_when_their_hash_matches(tmp_path, monkeypatch):
    good, bad = b"model bytes", b"voices bytes"
    monkeypatch.setattr(
        kokoro,
        "FILES",
        {"m.onnx": hashlib.sha256(good).hexdigest(), "v.bin": hashlib.sha256(b"other").hexdigest()},
    )
    results = kokoro.download(tmp_path, opener=_serving({"m.onnx": good, "v.bin": bad}))
    assert results["m.onnx"] == ""
    assert (tmp_path / "m.onnx").read_bytes() == good
    assert results["v.bin"].startswith("sha256")
    assert not (tmp_path / "v.bin").exists() and not (tmp_path / "v.bin.part").exists()

    def unreachable(url, timeout=0):
        raise AssertionError("a file already verified is not downloaded again")

    again = kokoro.download(tmp_path, opener=lambda url, timeout=0: (
        unreachable(url) if url.endswith("m.onnx") else io.BytesIO(b"other")
    ))
    assert again == {"m.onnx": "", "v.bin": ""}


def test_a_broken_connection_leaves_nothing_half_written(tmp_path, monkeypatch):
    monkeypatch.setattr(kokoro, "FILES", {"m.onnx": "0" * 64})

    def broken(url, timeout=0):
        raise OSError("connection reset")

    assert kokoro.download(tmp_path, opener=broken) == {"m.onnx": "connection reset"}
    assert list(tmp_path.iterdir()) == []


def test_the_pinned_files_are_the_release_ones():
    assert set(kokoro.FILES) == {"kokoro-v1.0.int8.onnx", "voices-v1.0.bin"}
    assert all(len(h) == 64 for h in kokoro.FILES.values())


# -- the real voice, where its files have been downloaded ----------------------
def test_the_real_voice_speaks_spanish_and_english(monkeypatch):
    folder = os.getenv("B1_KOKORO_TEST_DIR", "")
    if not (kokoro.engine_installed() and folder and kokoro.files_present(Path(folder))):
        pytest.skip("set B1_KOKORO_TEST_DIR to a folder with the Kokoro files")
    speaker = kokoro.KokoroSpeaker(Path(folder))
    for language, text in (("es", "La fábrica tiene tres tareas."), ("en", "The factory has three tasks.")):
        speaker.language = language
        samples, rate = speaker.synthesize(text)
        assert rate == 24_000
        assert len(samples) > rate  # more than a second of speech
        assert float(abs(samples).max()) > 0.1
