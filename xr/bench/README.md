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
language winning a close call in detection; "near word" is the grammar's
rule for a lone word within two letters of exactly one command ("Posa" is
"pausá", "Sagaib" is "seguí"; `src/voice/grammar.ts`), measured by scoring
the same transcripts again: no chatter became a command, and the few
misses it adds are a "which task?" question, not an action. "Short word"
is the device's other rule (`--short 0.9`): a phrase with under 0.9 s of
voice is taken in the page's language with no detection, since on a lone
word a small model's language guess is a coin toss; every synthetic lone
word is under that, and it saves the detection step (1.5 → 1.2 s per
phrase). Its cost is by design: a lone word in the other language is
heard in the page's.

| recognizer | es | en | s/phrase (this CPU) | where |
|---|---|---|---|---|
| grammar on the written phrases (old keyword list) | 23% | 58% | | |
| grammar on the written phrases | 100% | 100% | | |
| whisper tiny, detect | 46% | 82% | 1.6 | device |
| whisper tiny, detect + prompt | 55% | 87% | 1.1 | device |
| whisper tiny, detect + prompt, near word | 56% | 88% | 1.1 | device |
| whisper base, detect | 52% | 87% | 2.5 | device |
| whisper base, detect + prompt | 64% | 91% | 1.4 | device |
| whisper base, prior + prompt | 65% | 91% | 1.5 | device |
| whisper base, prior + prompt, near word | 68% | 93% | 1.5 | device |
| whisper base, prior + prompt, short word in the page's language | 67% | 91% | 1.2 | device |
| whisper base, prior + prompt, short word + near word (**the device**) | 70% | 93% | 1.2 | device |
| whisper small, prior + prompt | 75% | 94% | 3.0 | device |
| whisper small, prior + prompt, near word | 77% | 94% | 3.0 | device |
| faster-whisper small | 65% | 90% | | server |
| faster-whisper small + prompt | 77% | 95% | | server |
| faster-whisper large-v3-turbo (369 of 434, no prompt) | 74% | 91% | | server |
| faster-whisper large-v3-turbo + prompt | 81% | 91% | 11.2 | server |

What the numbers decided: the device default is **`base` with the prompt,
the prior, the short-word rule and the near-word rule** (70% / 93%).
`small` hears seven more Spanish commands in a hundred, at
twice the time per phrase and three times the download (about 240 MB
against 80), too much for a headset's first visit; `?stt=small` keeps it
within reach on a desktop. On the server, the prompt is worth more than a
model size: `small` with the prompt hears 77% of the Spanish commands,
`large-v3-turbo` with it 81%, at seven times the time per phrase on a CPU
(the server tier's default is `large-v3-turbo`; `SPEECH_STT_MODEL=small`
for a slow CPU). The weakest phrases are the lone Rioplatense imperatives:
"pausá" and "seguí" by themselves are heard by no model from any voice
("Posa", "Vos", "That's it"), while "pará un momento", "continuá" and
"esperá" are heard from every voice; the director's prompts and the judges'
examples use those. The synthetic voices are a hard test (one Piper voice says
"Lanzá" as "la ensal" to a person too); the owner's own recordings, under
`audio/real/`, are the measure that counts.

The voice detector (`public/silero_vad_v6.onnx`, sha256 `4cbf549b…`, the
sequence export with `h`/`c` state) was checked against the model shipped
in silero-vad 6.2.3 (`silero_vad_16k_sequence.onnx`, same interface):
over a quarter of the bank, scored against a loudness label per window,
ours agrees with the label better (mean AUC 0.876 against 0.823), so it
stays. A real microphone in a noisy room is the measure this misses.

```bash
cd xr/bench && npm install
B1_KOKORO_DIR=~/.b1/kokoro PIPER_VOICES_DIR=~/.b1/voices python synthesize.py
npx tsx measure.ts --models tiny,base
python transcribe_faster_whisper.py --model large-v3-turbo
npx tsx measure.ts --external results/fw-large-v3-turbo.jsonl
```
