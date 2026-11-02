# Voice bench

The numbers behind the room's voice. Not shipped with the app; its own
`package.json` keeps the measuring tools out of the app's dependencies.

- `phrases.json`: the bilingual phrase bank. Each phrase is what a person
  would say to the room (Rioplatense Spanish first, with tuteo and usted
  forms; English), the intent meant and, for a launch, the task. `none` is
  chatter the room must ignore. The grammar's unit test
  (`src/voice/grammar.test.ts`) holds it to this bank: every written
  phrase must be understood as meant.
- `synthesize.py`: renders the bank with several voices (Kokoro's `ef_dora`
  and `af_heart`, Piper voices from Argentina, Mexico, Spain and the US) to
  `audio/<voice>/<id>.wav`, 16 kHz mono. Your own recordings go under
  `audio/real/<id>.wav`; they are measured like any voice and matter more.
- `measure.ts`: runs recognizers over the audio and scores each transcript
  twice: word error rate (the recognizer alone) and whether the room's
  grammar understood the command meant (what the person experiences).
  Per language, per voice, per intent, with the misses listed.
  - `--models tiny,base,small`: Whisper in transformers.js, the weights the
    device would run (q8), with the language detected per phrase the way
    the device does it (`--language detect`), given (`force`, an upper
    bound) or fixed (`es`/`en`).
  - `--external results/<name>.jsonl`: transcripts from elsewhere, such as
    `transcribe_faster_whisper.py` (the server tier).
  - `--grammar-only`: the written phrases themselves, no audio.
- `results/*.md`: the reports, committed; the raw transcripts beside them
  are not.

```bash
cd xr/bench && npm install
B1_KOKORO_DIR=~/.b1/kokoro PIPER_VOICES_DIR=~/.b1/voices python synthesize.py
npx tsx measure.ts --models tiny,base
python transcribe_faster_whisper.py --model large-v3-turbo
npx tsx measure.ts --external results/fw-large-v3-turbo.jsonl
```
