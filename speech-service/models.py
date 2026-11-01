"""The voice model files: where they live, and fetching them once, checked.

Kokoro's two files (about 120 MB) come from the kokoro-onnx release and are
accepted only when their SHA-256 matches the hashes pinned here, the same
pins the desktop assistant uses (asistente-b1/b1/kokoro.py). faster-whisper
downloads its own model through huggingface_hub on first use.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
#: name -> sha256: a file that does not match is deleted, never loaded.
KOKORO_FILES = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
KOKORO_MODEL, KOKORO_VOICES = KOKORO_FILES


def kokoro_dir() -> Path:
    return Path(os.getenv("SPEECH_KOKORO_DIR", "/models/kokoro")).expanduser()


def kokoro_present(folder: Path | None = None) -> bool:
    folder = folder or kokoro_dir()
    return all((folder / name).is_file() for name in KOKORO_FILES)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_kokoro(folder: Path | None = None, *, opener=urllib.request.urlopen) -> dict[str, str]:
    """Fetch the model and the voices once; returns name -> "" or an error.

    Each file is written beside its final name and renamed into place only
    once its hash matches, so an interrupted or tampered download never
    becomes the file the voice loads.
    """
    folder = Path(folder or kokoro_dir())
    folder.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for name, expected in KOKORO_FILES.items():
        target = folder / name
        if target.is_file() and sha256(target) == expected:
            results[name] = ""
            continue
        partial = folder / f"{name}.part"
        try:
            with opener(f"{KOKORO_RELEASE}/{name}", timeout=60) as response, partial.open("wb") as out:
                for block in iter(lambda: response.read(1 << 20), b""):
                    out.write(block)
            got = sha256(partial)
            if got != expected:
                partial.unlink(missing_ok=True)
                results[name] = f"sha256 {got[:12]}... does not match {expected[:12]}..."
                continue
            partial.replace(target)
            results[name] = ""
        except Exception as exc:  # noqa: BLE001 - reported per file, the rest goes on
            partial.unlink(missing_ok=True)
            results[name] = str(exc)
    return results


if __name__ == "__main__":
    for name, error in download_kokoro().items():
        print(f"{name}: {error or 'ok'}")
