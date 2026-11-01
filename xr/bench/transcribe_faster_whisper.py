"""The server tier of the bench: faster-whisper over the rendered phrases.

Writes one JSON line per WAV (``voice``, ``id``, ``text``, ``language``,
``seconds``) that ``measure.ts`` scores like any other recognizer (``--external
results/<name>.jsonl``). The model is whatever the backend would run; the
default is the one with the best Spanish that still answers in a second or
two on a CPU.

    python bench/transcribe_faster_whisper.py --model large-v3-turbo \
        --out bench/results/fw-large-v3-turbo.jsonl

The language is detected per phrase among the two the app speaks (not
among Whisper's ninety-nine: a one-second "vení acá" is not Japanese),
unless ``--language`` forces one. With ``--prompts results/prompts.json``
(written by ``measure.ts --prompts``) the room's vocabulary in the detected
language is given as the text said before, which steers the decoding
toward the commands. Each clip gets half a second of silence at both ends,
as the device will add.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LANGS = ("es", "en")
SAMPLE_RATE = 16_000
PAD_SECONDS = 0.5


def read_wav(path: Path) -> np.ndarray:
    import wave  # noqa: PLC0415

    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == SAMPLE_RATE and handle.getnchannels() == 1 and handle.getsampwidth() == 2
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def padded(audio: np.ndarray, seconds: float = PAD_SECONDS) -> np.ndarray:
    pad = np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)
    return np.concatenate([pad, audio, pad])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--audio", default=str(HERE / "audio"))
    parser.add_argument("--out", default="")
    parser.add_argument("--language", default="", help="force es or en (default: detect per phrase)")
    parser.add_argument("--prompts", default="", help="JSON with the vocabulary hint per language")
    parser.add_argument("--compute", default="int8", help="ctranslate2 compute type")
    parser.add_argument("--beam", type=int, default=5)
    args = parser.parse_args(argv)

    from faster_whisper import WhisperModel  # noqa: PLC0415 - optional, slow import

    prompts: dict[str, str] = json.loads(Path(args.prompts).read_text(encoding="utf-8")) if args.prompts else {}
    name = f"fw-{args.model}" + ("-prompt" if prompts else "")
    out = Path(args.out or HERE / "results" / f"{name}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute)
    files = sorted(Path(args.audio).glob("*/*.wav"))
    with out.open("w", encoding="utf-8") as handle:
        for n, path in enumerate(files, 1):
            audio = padded(read_wav(path))
            started = time.perf_counter()
            language = args.language
            if not language:
                _, _, all_probs = model.detect_language(audio)
                probs = {code: p for code, p in all_probs if code in LANGS}
                language = max(probs, key=probs.get) if probs else "en"
            segments, _info = model.transcribe(
                audio,
                language=language,
                beam_size=args.beam,
                vad_filter=False,
                initial_prompt=prompts.get(language) or None,
                condition_on_previous_text=False,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            row = {
                "voice": path.parent.name,
                "id": path.stem,
                "text": text,
                "language": language,
                "seconds": round(time.perf_counter() - started, 3),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 50 == 0:
                print(f"{n}/{len(files)}", file=sys.stderr)
    print(f"{len(files)} transcripts → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
