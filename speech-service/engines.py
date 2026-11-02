"""The two engines behind the service, loaded once and lazily.

`WhisperEngine` wraps faster-whisper the way the voice layer wants it: the
language detected among the ones the application speaks (not Whisper's
ninety-nine), the page's language winning a close call, the application's
vocabulary as the text said before. `KokoroEngine` wraps kokoro-onnx with
a voice per language. Both are protocols too, so the API is tested with
stand-ins and no model on disk.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from audio import SAMPLE_RATE, padded
from models import KOKORO_MODEL, KOKORO_VOICES, kokoro_dir, kokoro_present

#: How much likelier (in log-probability) a language must be to overrule the page's.
PRIOR_MARGIN = 1.0

KOKORO_LANGUAGE = {"es": "es", "en": "en-us"}
DEFAULT_VOICES = {"es": "ef_dora", "en": "af_heart"}


@dataclass
class Transcript:
    text: str
    language: str
    seconds: float


class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray, *, languages: list[str], preferred: str | None, prompt: str) -> Transcript: ...

    def describe(self) -> dict: ...


class Synthesizer(Protocol):
    def speak(self, text: str, *, language: str, voice: str | None) -> tuple[np.ndarray, int]: ...

    def describe(self) -> dict: ...


def pick_language(probabilities: dict[str, float], languages: list[str], preferred: str | None, margin: float = PRIOR_MARGIN) -> str:
    """The likeliest of `languages`; a close call goes to `preferred`."""
    candidates = {code: probabilities.get(code, 0.0) for code in languages}
    if not candidates:
        return preferred or "en"
    best = max(candidates, key=candidates.get)  # type: ignore[arg-type]
    if preferred and preferred in candidates and preferred != best:
        gap = math.log(max(candidates[best], 1e-9)) - math.log(max(candidates[preferred], 1e-9))
        if gap < margin:
            return preferred
    return best


class WhisperEngine:
    """faster-whisper, loaded on first use (the download can take minutes)."""

    def __init__(self, model: str = "large-v3-turbo", device: str = "cpu", compute_type: str = "int8", beam_size: int = 5) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # noqa: PLC0415 - heavy, optional until used

                self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, samples: np.ndarray, *, languages: list[str], preferred: str | None, prompt: str) -> Transcript:
        import time  # noqa: PLC0415

        started = time.perf_counter()
        model = self._load()
        audio = padded(samples.astype(np.float32))
        if len(languages) == 1:
            language = languages[0]
        else:
            _, _, all_probs = model.detect_language(audio)
            language = pick_language(dict(all_probs), languages, preferred)
        segments, _info = model.transcribe(
            audio,
            language=language,
            beam_size=self.beam_size,
            vad_filter=False,
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(text=text, language=language, seconds=time.perf_counter() - started)

    def describe(self) -> dict:
        return {"engine": "faster-whisper", "model": self.model_name, "device": self.device, "compute_type": self.compute_type, "loaded": self._model is not None}


class KokoroEngine:
    """Kokoro-82M through kokoro-onnx: a voice per language, 24 kHz."""

    def __init__(self, folder: Path | None = None, voices: dict[str, str] | None = None) -> None:
        self.folder = Path(folder or kokoro_dir())
        self.voices = {**DEFAULT_VOICES, **(voices or {})}
        self._engine = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return kokoro_present(self.folder)

    def _load(self):
        with self._lock:
            if self._engine is None:
                from kokoro_onnx import Kokoro  # noqa: PLC0415 - heavy, optional until used

                self._engine = Kokoro(str(self.folder / KOKORO_MODEL), str(self.folder / KOKORO_VOICES))
        return self._engine

    def speak(self, text: str, *, language: str, voice: str | None) -> tuple[np.ndarray, int]:
        engine = self._load()
        samples, rate = engine.create(text, voice=voice or self.voices.get(language, DEFAULT_VOICES["en"]), lang=KOKORO_LANGUAGE.get(language, "en-us"))
        return np.asarray(samples, dtype=np.float32), int(rate)

    def describe(self) -> dict:
        return {"engine": "kokoro", "voices": self.voices, "files_present": self.available(), "loaded": self._engine is not None}


__all__ = ["DEFAULT_VOICES", "KokoroEngine", "PRIOR_MARGIN", "SAMPLE_RATE", "Synthesizer", "Transcriber", "Transcript", "WhisperEngine", "pick_language"]
