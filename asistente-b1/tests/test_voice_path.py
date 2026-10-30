"""The voice path without hardware: capture loop, TTS fallbacks, capability probes.

Nothing here opens a microphone or downloads a model. The point is that a
machine missing PortAudio, Piper or Whisper still runs — it says what is
missing instead of dying with a traceback in the middle of a sentence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from b1.audio import FRAME_MS, SAMPLE_RATE, Endpointer, Microphone, pcm_to_floats, record_phrase
from b1.speech import (
    ConsoleSpeaker,
    PiperSpeaker,
    Silence,
    SystemSpeaker,
    WhisperTranscriber,
    make_speaker,
    make_transcriber,
    mic_ready,
    piper_ready,
    stt_ready,
)


class _FakeStream:
    """Stands in for ``sounddevice.InputStream``: speech, then silence."""

    def __init__(self, frames: list[int]) -> None:
        self.frames = list(frames)
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def read(self, size: int) -> tuple[list[list[int]], bool]:
        level = self.frames.pop(0) if self.frames else 0
        return [[level] * size], False


def test_listen_returns_one_utterance_when_the_person_stops():
    loud, quiet = 12_000, 0
    levels = [quiet] * 10 + [loud] * 12 + [quiet] * 40
    mic = Microphone()
    mic._stream = _FakeStream(levels)  # noqa: SLF001 - simulating PortAudio is the point

    seen: list[float] = []
    endpointer = Endpointer(silence_ms=300)
    pcm = mic.listen(endpointer, on_level=seen.append)

    assert pcm, "no devolvió audio"
    assert pcm_to_floats(pcm), "el PCM quedó vacío"
    assert max(seen) > 0.1, "el nivel no llegó a la interfaz"
    assert len(pcm) % 2 == 0


def test_callback_errors_do_not_stop_capture():
    mic = Microphone()
    mic._stream = _FakeStream([0] * 10 + [12_000] * 12 + [0] * 40)  # noqa: SLF001

    def broken(_level: float) -> None:
        raise RuntimeError("la ventana se cerró")

    assert mic.listen(Endpointer(silence_ms=300), on_level=broken)


def test_reading_a_closed_microphone_is_a_sentence_not_a_traceback():
    with pytest.raises(RuntimeError, match="micrófono"):
        Microphone().frame()


def test_recording_without_sounddevice_explains_what_to_install():
    if mic_ready():
        pytest.skip("sounddevice está instalado: no hay fallo que probar")
    with pytest.raises(RuntimeError, match="sounddevice"):
        record_phrase()


def test_microphone_that_never_opened_closes_quietly():
    mic = Microphone()
    mic.__exit__(None, None, None)
    assert mic._stream is None  # noqa: SLF001


def test_speakers_fall_back_to_the_console(tmp_path, monkeypatch):
    # A machine with no Piper model and no system engine is the last resort.
    monkeypatch.setattr(SystemSpeaker, "detect", classmethod(lambda cls, **kw: None))
    assert isinstance(make_speaker(None), ConsoleSpeaker)
    assert isinstance(make_speaker(str(tmp_path / "no-existe.onnx")), ConsoleSpeaker)
    assert Silence().say("nada") is None


def test_piper_absent_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert PiperSpeaker.if_available("/tmp/voz.onnx") is None
    assert piper_ready("/tmp/voz.onnx") is False


def _fake_piper(tmp_path: Path, *, writes: bool) -> Path:
    script = tmp_path / "piper-falso"
    body = (
        "import sys, pathlib\n"
        "args = sys.argv[1:]\n"
        "target = pathlib.Path(args[args.index('--output_file') + 1])\n"
        + ("target.write_bytes(b'RIFF' + b'\\x00' * 32)\n" if writes else "sys.exit(3)\n")
    )
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_piper_failure_still_says_the_sentence(tmp_path, capsys):
    speaker = PiperSpeaker(tmp_path / "voz.onnx", executable=str(_fake_piper(tmp_path, writes=False)))
    speaker.say("Prueba de voz.")
    assert "Prueba de voz." in capsys.readouterr().out


def test_piper_without_a_player_prints_the_path(tmp_path, capsys):
    if mic_ready():
        pytest.skip("sounddevice está instalado: sonaría de verdad")
    speaker = PiperSpeaker(tmp_path / "voz.onnx", executable=str(_fake_piper(tmp_path, writes=True)))
    speaker.say("Listo.")
    out = capsys.readouterr().out
    assert "audio listo" in out
    speaker.stop()


def test_empty_text_is_not_synthesised(tmp_path, capsys):
    speaker = PiperSpeaker(tmp_path / "voz.onnx", executable=str(_fake_piper(tmp_path, writes=True)))
    speaker.say("   ")
    assert capsys.readouterr().out == ""


def test_transcriber_without_audio_returns_nothing():
    assert WhisperTranscriber("small").transcribe(b"") == ""


def test_transcriber_without_the_package_says_so(monkeypatch):
    transcriber = make_transcriber("small")
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RuntimeError, match="faster-whisper"):
        transcriber.transcribe(b"\x00\x01" * 160)


def test_capability_probes_never_raise():
    assert isinstance(stt_ready(), bool)
    assert isinstance(mic_ready(), bool)
    assert isinstance(piper_ready(None), bool)


def test_frame_geometry_matches_sixteen_kilohertz():
    assert SAMPLE_RATE == 16_000
    assert FRAME_MS == 30
    assert Microphone().frame_size == 480


# -- transcription language -------------------------------------------------


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class _Info:
    def __init__(self, language: str) -> None:
        self.language = language


class _FakeWhisper:
    """Answers the scripted transcripts, in order, and records the arguments."""

    def __init__(self, *answers: tuple[str, str]) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        text, language = self.answers.pop(0)
        return ([_Segment(text)] if text else []), _Info(language)


def test_a_pinned_language_reaches_whisper():
    transcriber = WhisperTranscriber("small", language="en")
    transcriber._model = _FakeWhisper(("how is it going", "en"))  # noqa: SLF001

    assert transcriber.transcribe(b"\x00\x01" * 80) == "how is it going"
    assert transcriber._model.calls[0]["language"] == "en"  # noqa: SLF001
    assert transcriber._model.calls[0]["vad_filter"] is False  # noqa: SLF001
    assert transcriber.last_language == "en"


def test_automatic_language_is_still_automatic():
    transcriber = WhisperTranscriber("small", language="auto")
    transcriber._model = _FakeWhisper(("hola que tal", "es"))  # noqa: SLF001

    assert transcriber.transcribe(b"\x00\x01" * 80) == "hola que tal"
    assert transcriber._model.calls[0]["language"] is None  # noqa: SLF001
    assert transcriber.last_language == "es"


def test_a_wrong_hint_is_retried_without_one():
    transcriber = WhisperTranscriber("small", language="es")
    transcriber._model = _FakeWhisper(("", "es"), ("open the board", "en"))  # noqa: SLF001

    assert transcriber.transcribe(b"\x00\x01" * 80) == "open the board"
    attempts = [call["language"] for call in transcriber._model.calls]  # noqa: SLF001
    assert attempts == ["es", None]
    assert transcriber.last_language == "en"


def test_a_good_hint_is_not_paid_for_twice():
    transcriber = WhisperTranscriber("small", language="es")
    transcriber._model = _FakeWhisper(("hola", "es"))  # noqa: SLF001

    transcriber.transcribe(b"\x00\x01" * 80)
    assert len(transcriber._model.calls) == 1  # noqa: SLF001


def test_the_window_can_cut_the_phrase_short_and_keep_the_audio():
    mic = Microphone()
    mic._stream = _FakeStream([12_000] * 12 + [0] * 40)  # noqa: SLF001
    calls = {"n": 0}

    def stop_after_eight_frames() -> bool:
        calls["n"] += 1
        return calls["n"] > 8

    pcm = mic.listen(Endpointer(silence_ms=300), should_stop=stop_after_eight_frames)

    assert pcm, "lo dicho antes de cortar se pierde"
    assert pcm_to_floats(pcm)

