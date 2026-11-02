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

## Results so far

Commands understood from the seven synthetic voices (`results/*.md` has
each run per voice and intent, with every miss). "Prompt" is the room's
vocabulary given to Whisper as the text said before; "prior" is the page's
language winning a close call in detection.

| recognizer | es | en | s/phrase (this CPU) | where |
|---|---|---|---|---|
| grammar on the written phrases (old keyword list) | 23% | 58% | | |
| grammar on the written phrases | 100% | 100% | | |
| whisper tiny, detect | 46% | 82% | 1.6 | device |
| whisper tiny, detect + prompt | 55% | 87% | 1.1 | device |
| whisper base, detect | 52% | 87% | 2.5 | device |
| whisper base, detect + prompt | 64% | 91% | 1.4 | device |
| whisper base, prior + prompt | 65% | 91% | 1.5 | device |
| whisper small, prior + prompt | 75% | 94% | 3.0 | device |
| faster-whisper small | 65% | 90% | | server |
| faster-whisper small + prompt | 77% | 95% | | server |
| faster-whisper large-v3-turbo (369 of 434, no prompt) | 74% | 91% | | server |

What the numbers decided: the device default is **`base` with the prompt
and the prior**. `small` hears ten more Spanish commands in a hundred, at
twice the time per phrase and three times the download (about 240 MB
against 80), too much for a headset's first visit; `?stt=small` keeps it
within reach on a desktop. On the server, the prompt is worth more than a
model size. The weakest phrases are the lone Rioplatense imperatives:
"pausá" and "seguí" by themselves are heard by no model from any voice
("Posa", "Vos", "That's it"), while "pará un momento", "continuá" and
"esperá" are heard from every voice; the director's prompts and the judges'
examples use those. The synthetic voices are a hard test (one Piper voice says
"Lanzá" as "la ensal" to a person too); the owner's own recordings, under
`audio/real/`, are the measure that counts.

```bash
cd xr/bench && npm install
B1_KOKORO_DIR=~/.b1/kokoro PIPER_VOICES_DIR=~/.b1/voices python synthesize.py
npx tsx measure.ts --models tiny,base
python transcribe_faster_whisper.py --model large-v3-turbo
npx tsx measure.ts --external results/fw-large-v3-turbo.jsonl
```
