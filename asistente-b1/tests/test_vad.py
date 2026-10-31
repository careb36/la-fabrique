"""What ends a phrase: a voice detector when there is one, loudness otherwise."""

from __future__ import annotations

import math

import pytest

from b1 import vad
from b1.audio import Endpointer
from b1.config import Settings

FRAME = 480  # 30 ms at 16 kHz, what the microphone hands over


def frames(level: float, count: int) -> list[list[float]]:
    return [[level] * FRAME for _ in range(count)]


class ScriptedDetector:
    """Says speech for the frames it was told to, whatever their loudness."""

    def __init__(self, answers):
        self.answers = list(answers)

    def is_speech(self, frame):
        return self.answers.pop(0) if self.answers else False


# -- the endpointer with a detector -------------------------------------------
def test_loud_noise_does_not_open_a_phrase_when_the_detector_hears_no_voice():
    noise = frames(12_000, 40)
    energy = Endpointer()
    assert any(energy.feed(f) is not None or energy.collecting for f in noise)

    detector = Endpointer(detector=ScriptedDetector([False] * 40))
    assert all(detector.feed(f) is None for f in noise)
    assert not detector.collecting


def test_a_soft_voice_opens_and_silence_closes_the_phrase():
    # Too quiet for the energy rule, but the detector hears a voice.
    soft = frames(150, 10)
    quiet = frames(150, 30)
    endpointer = Endpointer(detector=ScriptedDetector([True] * 10 + [False] * 30))
    results = [endpointer.feed(f) for f in soft + quiet]
    utterances = [r for r in results if r]
    assert len(utterances) == 1
    assert len(utterances[0]) >= 10 * FRAME * 2  # the voiced frames are in it

    assert Endpointer().feed(soft[0]) is None
    energy = Endpointer()
    for f in soft:
        energy.feed(f)
    assert not energy.collecting


# -- the streaming detector, with a stand-in for the model --------------------
class FakeSession:
    """Answers each window with the next probability and records the inputs."""

    def __init__(self, probabilities):
        self.probabilities = list(probabilities)
        self.inputs = []

    def run(self, _outputs, feeds):
        import numpy as np

        self.inputs.append({k: v.copy() for k, v in feeds.items()})
        p = self.probabilities.pop(0) if self.probabilities else 0.0
        return np.array([[p]], dtype="float32"), feeds["h"] + 1, feeds["c"] + 1


def test_frames_are_regrouped_into_model_windows_with_context_and_state():
    np = pytest.importorskip("numpy")
    session = FakeSession([0.1, 0.1, 0.1])
    detector = vad.SileroDetector(session)
    detector.is_speech([1000.0] * FRAME)
    assert session.inputs == []  # 480 samples: not a full window yet
    detector.is_speech([2000.0] * FRAME)
    assert len(session.inputs) == 1  # 960 samples: one window of 512
    first = session.inputs[0]
    assert first["input"].shape == (1, vad.CONTEXT + vad.WINDOW)
    assert np.all(first["input"][0, : vad.CONTEXT] == 0)  # no context before the first
    for _ in range(2):
        detector.is_speech([3000.0] * FRAME)
    second = session.inputs[1]
    # The context is the end of the previous window, and the state is carried.
    assert np.allclose(second["input"][0, : vad.CONTEXT], first["input"][0, -vad.CONTEXT :])
    assert np.all(second["h"] == 1) and np.all(second["c"] == 1)
    assert first["input"].dtype == np.float32 and first["input"].max() <= 1.0


def test_speech_starts_at_the_threshold_and_ends_below_the_release():
    pytest.importorskip("numpy")
    detector = vad.SileroDetector(FakeSession([0.4, 0.6, 0.4, 0.3]), threshold=0.5, release=0.35)
    window = [0.0] * vad.WINDOW
    assert detector.is_speech(window) is False  # 0.4: not yet
    assert detector.is_speech(window) is True  # 0.6: starts
    assert detector.is_speech(window) is True  # 0.4: a dip inside a word
    assert detector.is_speech(window) is False  # 0.3: ends


# -- choosing and falling back --------------------------------------------------
def test_energy_is_chosen_or_used_when_silero_is_missing(monkeypatch, tmp_path):
    assert vad.load_detector("energy") is None
    monkeypatch.setenv("B1_VAD_MODEL", str(tmp_path / "missing.onnx"))
    assert vad.load_detector("silero") is None
    assert "B1_VAD" in vad.describe("energy", "es")
    assert "Silero" in vad.describe("silero", "en")  # unavailable, and says so


def test_the_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("B1_VAD", "Energy")
    assert Settings().apply_env().vad == "energy"
    monkeypatch.setenv("B1_VAD", "whatever")
    assert Settings().apply_env().vad == "silero"


# -- the real model, where faster-whisper is installed --------------------------
def _signal(kind: str, np, seconds: float = 1.0):
    n = int(16_000 * seconds)
    t = np.arange(n) / 16_000
    if kind == "noise":
        return np.random.default_rng(1).normal(0, 6000, n)
    if kind == "hum":
        return 8000 * np.sin(2 * math.pi * 100 * t)
    # A vowel-like sound: harmonics of a voice's pitch shaped by two formants,
    # changing every quarter second the way syllables do.
    out = np.zeros(n)
    quarter = n // 4
    for i, (f0, formants) in enumerate(
        [(120, (700, 1200)), (130, (300, 2300)), (110, (500, 900)), (125, (400, 2000))]
    ):
        part = t[i * quarter : (i + 1) * quarter]
        for k in range(1, 40):
            amp = sum(math.exp(-(((k * f0) - f) / 120) ** 2) for f in formants)
            out[i * quarter : (i + 1) * quarter] += amp * np.sin(2 * math.pi * k * f0 * part)
    return out / np.abs(out).max() * 12_000


def _speech_frames(detector, signal):
    detector.reset()
    return [
        detector.is_speech(signal[i : i + FRAME].tolist())
        for i in range(0, len(signal) - FRAME, FRAME)
    ]


def test_the_real_model_hears_a_voice_and_not_noise():
    np = pytest.importorskip("numpy")
    detector = vad.load_detector("silero")
    if detector is None:
        pytest.skip("Silero (faster-whisper) is not installed")
    assert not any(_speech_frames(detector, _signal("noise", np)))
    assert not any(_speech_frames(detector, _signal("hum", np)))
    assert sum(_speech_frames(detector, _signal("voice", np))) > 10


def test_with_the_real_model_a_fan_never_starts_listening():
    np = pytest.importorskip("numpy")
    detector = vad.load_detector("silero")
    if detector is None:
        pytest.skip("Silero (faster-whisper) is not installed")
    hum = _signal("hum", np, seconds=2.0)
    chunks = [hum[i : i + FRAME].tolist() for i in range(0, len(hum) - FRAME, FRAME)]
    energy = Endpointer()
    silero = Endpointer(detector=detector)
    for chunk in chunks:
        energy.feed(chunk)
        silero.feed(chunk)
    assert energy.collecting  # loudness alone took the fan for a voice
    assert not silero.collecting
