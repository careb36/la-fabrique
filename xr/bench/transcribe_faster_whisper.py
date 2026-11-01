"""The server tier of the bench: faster-whisper over the rendered phrases.

Writes one JSON line per WAV (``voice``, ``id``, ``text``, ``language``,
``seconds``) that ``measure.ts`` scores like any other recognizer (``--external
results/<name>.jsonl``). The model is whatever the backend would run; the
default is the one with the best Spanish that still answers in a second or
two on a CPU.

    python bench/transcribe_faster_whisper.py --model large-v3-turbo \
        --out bench/results/fw-large-v3-turbo.jsonl

Language is detected per phrase unless ``--language`` forces one, the same
choice the device makes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--audio", default=str(HERE / "audio"))
    parser.add_argument("--out", default="")
    parser.add_argument("--language", default="", help="force es or en (default: detect per phrase)")
    parser.add_argument("--compute", default="int8", help="ctranslate2 compute type")
    parser.add_argument("--beam", type=int, default=5)
    args = parser.parse_args(argv)

    from faster_whisper import WhisperModel  # noqa: PLC0415 - optional, slow import

    out = Path(args.out or HERE / "results" / f"fw-{args.model}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute)
    files = sorted(Path(args.audio).glob("*/*.wav"))
    with out.open("w", encoding="utf-8") as handle:
        for n, path in enumerate(files, 1):
            started = time.perf_counter()
            segments, info = model.transcribe(
                str(path), language=args.language or None, beam_size=args.beam, vad_filter=False
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            row = {
                "voice": path.parent.name,
                "id": path.stem,
                "text": text,
                "language": info.language,
                "seconds": round(time.perf_counter() - started, 3),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 50 == 0:
                print(f"{n}/{len(files)}", file=sys.stderr)
    print(f"{len(files)} transcripts → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
