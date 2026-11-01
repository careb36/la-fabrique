"""Kokoro-82M: a small open neural voice that speaks Spanish and English.

Kokoro (Apache-2.0) sounds closer to a person than Piper's medium voices and
runs on the CPU faster than real time. ``kokoro-onnx`` runs it with
onnxruntime and phonemizes with a bundled espeak-ng, so nothing else has to be
installed on the machine. The model and the voices (about 120 MB) are
downloaded once by ``b1 --voices`` and checked against the hashes below.

Without ``kokoro-onnx`` or its files, the speaker chain moves on to Piper,
then the system voice, then the console.
"""

from __future__ import annotations

import functools
import hashlib
import os
import tempfile
import urllib.request
import wave
from pathlib import Path

from .i18n import normalize, t

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
#: name -> sha256: a file that does not match is deleted, never loaded.
FILES = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
MODEL, VOICES = FILES
#: Kokoro's language codes for the two the assistant speaks.
LANGUAGES = {"es": "es", "en": "en-us"}
DEFAULT_VOICES = {"es": "ef_dora", "en": "af_heart"}


def kokoro_dir() -> Path:
    override = os.getenv("B1_KOKORO_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from .config import app_dir  # noqa: PLC0415 - avoids an import cycle

    return app_dir() / "kokoro"


def files_present(folder: Path | None = None) -> bool:
    folder = folder or kokoro_dir()
    return all((folder / name).is_file() for name in FILES)


def engine_installed() -> bool:
    try:
        import kokoro_onnx  # noqa: F401,PLC0415 - presence check only
    except Exception:  # noqa: BLE001
        return False
    return True


@functools.lru_cache(maxsize=1)
def _engine(model: str, voices: str):
    from kokoro_onnx import Kokoro  # noqa: PLC0415 - optional

    return Kokoro(model, voices)


class KokoroSpeaker:
    """Says text with Kokoro, a voice per language, through ``sounddevice``."""

    name = "kokoro"

    def __init__(
        self,
        folder: Path,
        *,
        voices: dict[str, str] | None = None,
        output: str = "",
        language: str = "es",
        speed: float = 1.0,
    ) -> None:
        self.folder = Path(folder)
        self.voices = {**DEFAULT_VOICES, **{k: v for k, v in (voices or {}).items() if v}}
        self.output = output
        self.language = normalize(language)
        self.speed = speed

    @classmethod
    def if_available(
        cls,
        *,
        voice: str = "",
        voice_en: str = "",
        output: str = "",
        language: str = "es",
    ) -> "KokoroSpeaker | None":
        folder = kokoro_dir()
        if not engine_installed() or not files_present(folder):
            return None
        return cls(folder, voices={"es": voice, "en": voice_en}, output=output, language=language)

    def voice_for(self, language: str | None = None) -> str:
        return self.voices[normalize(language or self.language)]

    def synthesize(self, text: str):
        """The samples (float32) and their rate for one piece of text."""
        engine = _engine(str(self.folder / MODEL), str(self.folder / VOICES))
        language = normalize(self.language)
        return engine.create(
            text, voice=self.voice_for(language), speed=self.speed, lang=LANGUAGES[language]
        )

    def say(self, text: str) -> None:
        from .speech import ConsoleSpeaker  # noqa: PLC0415 - avoids an import cycle

        text = (text or "").strip()
        if not text:
            return
        try:
            samples, rate = self.synthesize(text)
        except Exception:  # noqa: BLE001 - a broken voice must not lose the words
            ConsoleSpeaker(self.language).say(text)
            return
        try:
            self._play(samples, rate)
        except Exception:  # noqa: BLE001 - no device: hand over the audio instead
            path = write_wav(samples, rate, Path(tempfile.gettempdir()) / "b1-voz.wav")
            ConsoleSpeaker(self.language).say(t(self.language, "speech.audio_ready", path=path))

    def _play(self, samples, rate: int) -> None:
        import sounddevice as sd  # noqa: PLC0415 - optional dependency

        from . import devices  # noqa: PLC0415 - avoids an import cycle

        # Resolved per answer: a headset plugged in between two answers gets the next.
        sd.play(samples, rate, device=devices.resolve(self.output, devices.OUTPUT, rate=rate))
        sd.wait()

    def stop(self) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415

            sd.stop()
        except Exception:  # noqa: BLE001 - nothing playing, nothing to stop.
            pass


def write_wav(samples, rate: int, path: Path) -> Path:
    """PCM16 mono WAV from float samples in [-1, 1]."""
    import numpy as np  # noqa: PLC0415 - comes with kokoro-onnx

    pcm = (np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(folder: Path | None = None, *, opener=urllib.request.urlopen) -> dict[str, str]:
    """Fetch the model and the voices once; returns name -> "" or an error.

    Each file is written beside its final name and only renamed into place
    once its hash matches, so an interrupted or tampered download never
    becomes the file Kokoro loads.
    """
    folder = Path(folder or kokoro_dir())
    folder.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for name, expected in FILES.items():
        target = folder / name
        if target.is_file() and _sha256(target) == expected:
            results[name] = ""
            continue
        partial = folder / f"{name}.part"
        try:
            with opener(f"{RELEASE}/{name}", timeout=60) as response, partial.open("wb") as out:
                for block in iter(lambda: response.read(1 << 20), b""):
                    out.write(block)
            got = _sha256(partial)
            if got != expected:
                partial.unlink(missing_ok=True)
                results[name] = f"sha256 {got[:12]}… ≠ {expected[:12]}…"
                continue
            partial.replace(target)
            results[name] = ""
        except Exception as exc:  # noqa: BLE001 - reported per file, the rest goes on
            partial.unlink(missing_ok=True)
            results[name] = str(exc)
    return results
