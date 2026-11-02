"""Speak the phrase bank with several synthetic voices, one WAV per phrase.

The recognizers are measured on audio, so each phrase in ``phrases.json`` is
rendered by every voice listed in ``VOICES`` that is installed: Kokoro
(``ef_dora`` for Spanish, ``af_heart`` for English, the voices the B1
assistant uses) and Piper voices from three Spanish-speaking countries and
two English ones, so a recognizer tuned to one accent is caught. Output is
16 kHz mono PCM16 under ``audio/<voice>/<phrase id>.wav``, the rate Whisper
and Silero read; the folder is not committed.

A person's own recordings go under ``audio/real/<phrase id>.wav`` (any
rate; ``measure.ts`` resamples) and are measured like any other voice. The
synthetic voices measure the recognizers in the clean case; the real ones
measure them in the case that matters.

Usage (with the voice extra installed, ``kokoro-onnx`` and ``piper-tts``):

    python bench/synthesize.py [--voices es-dora,en-heart,...] [--out bench/audio]

Model files: Kokoro's in ``B1_KOKORO_DIR`` (or ``~/.b1/kokoro``), Piper's in
``PIPER_VOICES_DIR`` (``<key>.onnx`` and ``<key>.onnx.json``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TARGET_RATE = 16_000


@dataclass(frozen=True)
class Voice:
    name: str  # folder name under audio/
    lang: str  # "es" or "en": only phrases in this language are rendered
    engine: str  # "kokoro" or "piper"
    model: str  # Kokoro voice id, or Piper voice key


VOICES = (
    Voice("es-dora", "es", "kokoro", "ef_dora"),
    Voice("en-heart", "en", "kokoro", "af_heart"),
    Voice("es-ar-daniela", "es", "piper", "es_AR-daniela-high"),
    Voice("es-mx-claude", "es", "piper", "es_MX-claude-high"),
    Voice("es-es-davefx", "es", "piper", "es_ES-davefx-medium"),
    Voice("en-us-lessac", "en", "piper", "en_US-lessac-high"),
    Voice("en-us-ryan", "en", "piper", "en_US-ryan-high"),
)

KOKORO_LANG = {"es": "es", "en": "en-us"}


def resample(samples: np.ndarray, rate: int, target: int = TARGET_RATE) -> np.ndarray:
    """Linear resampling: enough for speech going to a recognizer."""
    if rate == target:
        return samples.astype(np.float32)
    duration = len(samples) / rate
    n = int(round(duration * target))
    src = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    dst = np.linspace(0.0, duration, num=n, endpoint=False)
    return np.interp(dst, src, samples).astype(np.float32)


def write_wav(samples: np.ndarray, rate: int, path: Path) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


class KokoroEngine:
    def __init__(self) -> None:
        from kokoro_onnx import Kokoro  # noqa: PLC0415 - optional

        folder = Path(os.getenv("B1_KOKORO_DIR") or Path.home() / ".b1" / "kokoro")
        self._engine = Kokoro(str(folder / "kokoro-v1.0.int8.onnx"), str(folder / "voices-v1.0.bin"))

    def say(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        samples, rate = self._engine.create(text, voice=voice.model, lang=KOKORO_LANG[voice.lang])
        return np.asarray(samples, dtype=np.float32), int(rate)


class PiperEngine:
    def __init__(self) -> None:
        from piper import PiperVoice  # noqa: PLC0415 - optional

        self._load = PiperVoice.load
        self._folder = Path(os.getenv("PIPER_VOICES_DIR") or Path.home() / ".b1" / "voices")
        self._voices: dict[str, object] = {}

    def available(self, voice: Voice) -> bool:
        return (self._folder / f"{voice.model}.onnx").is_file()

    def say(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        model = self._voices.get(voice.model)
        if model is None:
            model = self._voices[voice.model] = self._load(str(self._folder / f"{voice.model}.onnx"))
        chunks = list(model.synthesize(text))  # type: ignore[attr-defined]
        pcm = np.concatenate([c.audio_int16_array for c in chunks]) if chunks else np.zeros(0, np.int16)
        return pcm.astype(np.float32) / 32768.0, int(model.config.sample_rate)  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--voices", default="", help="comma-separated voice names (default: every installed one)")
    parser.add_argument("--out", default=str(HERE / "audio"))
    parser.add_argument("--force", action="store_true", help="re-render files that already exist")
    args = parser.parse_args(argv)

    bank = json.loads((HERE / "phrases.json").read_text(encoding="utf-8"))
    wanted = {v.strip() for v in args.voices.split(",") if v.strip()}
    out = Path(args.out)
    engines: dict[str, object] = {}
    rendered = skipped = 0

    for voice in VOICES:
        if wanted and voice.name not in wanted:
            continue
        try:
            if voice.engine not in engines:
                engines[voice.engine] = KokoroEngine() if voice.engine == "kokoro" else PiperEngine()
            engine = engines[voice.engine]
            if voice.engine == "piper" and not engine.available(voice):  # type: ignore[attr-defined]
                print(f"{voice.name}: {voice.model}.onnx not installed, skipped", file=sys.stderr)
                continue
        except Exception as exc:  # noqa: BLE001 - one missing engine must not stop the others
            print(f"{voice.name}: {voice.engine} unavailable ({exc}), skipped", file=sys.stderr)
            continue
        for phrase in bank["phrases"]:
            if phrase["lang"] != voice.lang:
                continue
            target = out / voice.name / f"{phrase['id']}.wav"
            if target.is_file() and not args.force:
                skipped += 1
                continue
            samples, rate = engine.say(phrase["text"], voice)  # type: ignore[attr-defined]
            write_wav(resample(samples, rate), TARGET_RATE, target)
            rendered += 1
        print(f"{voice.name}: done")
    print(f"rendered {rendered}, kept {skipped} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
