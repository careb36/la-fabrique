"""Is the person talking? Silero VAD, with the energy rule as the fallback.

The energy endpointer in ``audio.py`` hears loudness, not voice: a fan, a
keyboard or a door counts as speech, and a soft voice in a noisy room may not.
Silero is a small neural voice detector that tells the two apart. It ships
inside ``faster-whisper``, which the voice extra already installs for
transcription, so it costs no new dependency and no download.

Without ``faster-whisper`` (or with ``B1_VAD=energy``) nothing changes: the
endpointer keeps its energy rule.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Sequence

from .i18n import normalize, t

SAMPLE_RATE = 16_000
# Silero v6 reads 512 new samples (32 ms at 16 kHz) plus the 64 before them.
WINDOW = 512
CONTEXT = 64
CHOICES = ("silero", "energy")


def normalize_choice(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text if text in CHOICES else "silero"


def model_path() -> Path | None:
    """The Silero ONNX file: ``B1_VAD_MODEL``, else the one faster-whisper ships."""
    override = os.getenv("B1_VAD_MODEL", "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    try:
        import faster_whisper  # noqa: PLC0415 - optional
    except Exception:  # noqa: BLE001 - missing extra: the energy rule stays
        return None
    path = Path(faster_whisper.__file__).resolve().parent / "assets" / "silero_vad_v6.onnx"
    return path if path.is_file() else None


@functools.lru_cache(maxsize=1)
def _session(path: str):
    import onnxruntime  # noqa: PLC0415 - optional, comes with faster-whisper

    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    options.log_severity_level = 4
    return onnxruntime.InferenceSession(
        path, providers=["CPUExecutionProvider"], sess_options=options
    )


class SileroDetector:
    """Feed it the microphone's frames; it says whether a voice is in them.

    The model keeps a state between windows, so it is fed in order, one
    32 ms window at a time, whatever size the microphone's frames are. It
    starts calling it speech at ``threshold`` and stops below ``release``, so
    a word that dips for a moment does not end the phrase.
    """

    name = "silero"

    def __init__(self, session, *, threshold: float = 0.5, release: float = 0.35) -> None:
        import numpy  # noqa: PLC0415 - optional, comes with faster-whisper

        self._np = numpy
        self.session = session
        self.threshold = threshold
        self.release = min(release, threshold)
        self.probability = 0.0
        self.reset()

    def reset(self) -> None:
        np = self._np
        self._h = np.zeros((1, 1, 128), dtype="float32")
        self._c = np.zeros((1, 1, 128), dtype="float32")
        self._context = np.zeros(CONTEXT, dtype="float32")
        self._pending = np.zeros(0, dtype="float32")
        self._speaking = False

    def is_speech(self, frame: Sequence[float]) -> bool:
        np = self._np
        samples = np.asarray(frame, dtype="float32") / 32768.0
        self._pending = np.concatenate([self._pending, samples])
        while len(self._pending) >= WINDOW:
            window, self._pending = self._pending[:WINDOW], self._pending[WINDOW:]
            self.probability = self._run(window)
            if self._speaking:
                self._speaking = self.probability >= self.release
            else:
                self._speaking = self.probability >= self.threshold
        return self._speaking

    def _run(self, window) -> float:
        np = self._np
        batch = np.concatenate([self._context, window])[np.newaxis, :]
        output, self._h, self._c = self.session.run(
            None, {"input": batch, "h": self._h, "c": self._c}
        )
        self._context = window[-CONTEXT:]
        return float(np.asarray(output).reshape(-1)[0])


def load_detector(choice: str | None = "silero") -> SileroDetector | None:
    """A fresh detector, or ``None`` when the energy rule should decide."""
    if normalize_choice(choice) != "silero":
        return None
    path = model_path()
    if path is None:
        return None
    try:
        return SileroDetector(_session(str(path)))
    except Exception:  # noqa: BLE001 - a broken runtime falls back, it does not crash
        return None


def describe(choice: str | None, language: str = "es") -> str:
    """One line for ``b1 --check``: which detector ends the phrase, and why."""
    language = normalize(language)
    if normalize_choice(choice) == "energy":
        return t(language, "vad.energy_chosen")
    if load_detector("silero") is None:
        return t(language, "vad.energy_fallback")
    return t(language, "vad.silero")
