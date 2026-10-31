# Assistant B1

*English · [Español](README.es.md)*

A desktop assistant that listens, thinks and acts. Its concrete job is to run
**La Fabrique** — a software factory staffed by agents — by voice: ask for its
status, plan a sprint, dispatch it, pause it, approve it, or have it build a
project on the spot.

It is its own implementation, written from scratch, under **Apache-2.0**. It
contains no code, text, icons or prompts from any other assistant.

```
  microphone ──▶ end of speech ──▶ faster-whisper ──▶ model (tools) ──▶ output voice ──▶ speaker
                                   (local, MIT)       OpenAI-compat     piper or the system's
                                                          │
                                                          ├─▶ La Fabrique  /v1/voice/status
                                                          ├─▶ La Fabrique  /v1/voice/command
                                                          └─▶ La Fabrique  /v1/voice/build
```

## Why this is original

Three things, and all three can be checked in this repository:

1. **The code was written for this project.** Not a single file is copied from
   another assistant. The core depends on nothing outside the standard library:
   the model's HTTP client, the tool registry, end-of-speech detection and the
   conversation loop are all our own code.
2. **So is the text.** Every prompt, every line of the guide and every error
   message was written here. Text is what usually gives a copy away even when
   the code has been rewritten.
3. **A test measures it.**

```bash
python tools/similarity_check.py ../profesor3
# 15 own files / 126 in the other tree · prose: 0 matches of 8 words
#   · code: 0 blocks of 14 tokens
# Original: no prose or code blocks in common.
```

The check compares two different things: **prose** (comments, docstrings and
literals longer than two words, in runs of 8) and **code** (every token, in runs
of 14). The second measure is what tells "two programs that use QTimer the same
way" apart from "a copied block". The test runs in `tests/test_originality.py`.

None of this is legal advice: originality is shown by the code and by these
measurements, and if you are going to sell it, have a lawyer review the package.

## What it can do with the factory

| You say | What happens |
|---|---|
| "how is the factory doing?" | reads the real status: sprint, tasks per stage, what is waiting for approval |
| "who is on the team?" | lists the agents (PO, architect, scrum master, devs, QA) |
| "plan a sprint for a coffee landing page" | drafts the plan with the factory's model |
| "create a sprint from that" | creates it **paused**, on purpose |
| "dispatch" / "pause" / "resume" | moves the sprint |
| "approve the delivery" | approves the pending run |
| "build a page with pricing" | builds it in seconds and opens it in the browser |

The rule that makes this usable out loud: **the factory returns a sentence
already written** (`speech`) and the assistant says it almost word for word. The
model picks the tool; it does not make up the result. If the backend does not
answer, the error is said in one sentence; it never pretends that it worked.

## Security

- **Actions that decide or start work wait for your confirmation.** `aprobar`
  (approve), `rechazar` (reject), `despachar` (dispatch), `reanudar` (resume)
  and `asignar` (assign) do not run when the model asks for them: the assistant
  asks you, and sends them only if your next sentence is "yes, confirm" (or
  «sí, confirmo»). That check lives in the code, not in the prompt, so text the
  model reads (a task title, a rejection note) cannot confirm them for you.
- **It only opens the factory's previews** (`<factory>/v1/voice/build/...`),
  never any other link that shows up in an answer.
- **Keys do not follow redirects to another host**, and they never travel over
  unencrypted `http://` to another machine: with the factory or the model on
  another computer, use `https://` (or `B1_ALLOW_INSECURE_HTTP=1`, only on a
  trusted network).
- **`config.json` is created with 0600 permissions** (its folder, 0700): it
  holds the model key and the voice key.
- **The system voice never runs the text it reads**: on Windows it travels as
  encoded data, not as PowerShell code.

## Installation

```bash
python -m pip install -e ".[ui,voice]"   # or: pip install -r requirements.txt
b1 --init                                # writes ~/.asistente-b1/config.json
b1 --check                               # what is installed and whether the services answer
b1                                       # opens the window
```

Settings (the file `~/.asistente-b1/config.json`, or environment variables,
which win over the file):

| Variable | Purpose |
|---|---|
| `B1_MODEL_BASE_URL` | an endpoint compatible with `/chat/completions` (NVIDIA `integrate.api.nvidia.com`, Token Factory, OpenAI, vLLM, Ollama) |
| `B1_MODEL_API_KEY` | the provider's key (`nvapi-…` for NVIDIA's gateway) |
| `B1_MODEL` | model id (default `nvidia/nemotron-3-ultra-550b-a55b`) |
| `B1_MODEL_THINKING` | `true` asks Nemotron for its reasoning (`chat_template_kwargs`) |
| `B1_MODEL_MAX_TOKENS` | cap on the answer; the reasoning is paid out of it |
| `B1_MODEL_TOP_P`, `B1_MODEL_TEMPERATURE`, `B1_MODEL_TIMEOUT` | sampling and per-turn wait |
| `B1_FACTORY_URL` | where the factory is (default `http://127.0.0.1:8000`) |
| `B1_VOICE_KEY` | the `X-Voice-Key` the factory expects |
| `B1_LANGUAGE` | `es` / `en`: the language the conversation starts in |
| `B1_STT_LANGUAGE` | `auto` (follows the conversation), or `es` / `en` to fix what it listens for |
| `B1_STT_MODEL` | faster-whisper model size (`tiny`, `base`, `small`…) |
| `B1_TTS_VOICE` | Piper voice for Spanish: path to an `.onnx` file or a name (`es_ES-sharvard-medium`) |
| `B1_TTS_VOICE_EN` | Piper voice for English (`en_US-amy-medium`) |
| `B1_MIC_DEVICE` | microphone name; empty means whatever the system picks |
| `B1_SPEAKER_DEVICE` | audio output name; empty means the system's |

The voice key and the model key can be entered in **Settings**, which also has
test buttons: model, factory, microphone and speaker.

## Microphone and audio output

On a laptop with a built-in microphone, the webcam's microphone and a headset,
the "system default" changes by itself every time you plug something in — and
that is where "it doesn't hear me" starts. **Settings** lets you choose the
microphone and the output, and test them right away:

![Audio settings](docs/ajustes-audio.png)

* The list shows each device **only once**, without aliases such as
  "Sound Mapper" or `default`, which are not hardware but "whatever the system
  wants". That is exactly what the *System (default)* option is.
* The **name** is saved, not the number: PortAudio renumbers devices when you
  plug one in, so a saved index ends up pointing at something else. If the
  chosen device is gone, the default is used and `b1 --check` says so instead of
  failing.
* "Test microphone" records three seconds and moves a bar with what comes in,
  so you can see it is listening before it finishes.
* "Test speaker" plays a beep through the chosen output: only the person can
  confirm that one; the program cannot guess whether it came out of the speaker.

## Voice: what it speaks and in which language

Spanish and English are on equal footing: it is not a translation of the
interface, it is the same program speaking one language or the other.

* **Listening.** Whisper is started with the conversation's language as a hint.
  If it returns nothing with that hint — which happens when someone switches
  language mid-sentence — the transcription is repeated without the hint and the
  model's detection wins. With `B1_STT_LANGUAGE=es` or `=en` the language is
  fixed and never guessed.
* **Speaking.** Piper first, if its binary and model are there; otherwise the
  system voice (SAPI on Windows, `say` on macOS, `espeak-ng`/`spd-say` on Linux)
  chosen by the sentence's language; and if there is none, the text on the
  console. It never goes silent without saying why: if the engine exists but
  cannot play, the sentence is printed and, once, the reason.
* **Piper ships without voices.** `b1 --voices` downloads the two configured
  voices once to `~/.asistente-b1/voces`; after that it can speak offline.
  Without that step, the system voice still covers the language.
* **The factory answers in the language too.** Every call to `/v1/voice/*`
  carries `language`, so the sentence the factory has already written arrives in
  the conversation's language; if one ever arrived in another, the prompt asks
  for it to be said in the conversation's language with the same figures.
* **The switch happens in the same turn.** The person speaks English, the
  assistant answers in English, and the window — status title, buttons, guide —
  changes with the answer. Settings can pin `es` or `en`.

## Modes

```bash
b1            # full window: orb, transcript and guide panel
b1 --orb      # just the orb, borderless and always on top
b1 --text     # console, no microphone or Qt
b1 --guide    # prints the factory guide
b1 --voices   # downloads the configured Piper voices once
b1 --speak "Hello"         # says that sentence and exits (voice test)
b1 --language en           # starts in English
b1 --check    # diagnostics
```

Without a microphone or Qt installed, the assistant starts in text mode instead
of breaking: each optional piece is detected and reported.

## How it is built

```
b1/
  app.py          CLI: window, orb, console, diagnostics
  assistant.py    turn loop: history, tools, voice
  llm.py          /chat/completions client with tool calling (stdlib only)
  tools.py        tool declaration + validation + dispatch
  fabrica.py      /v1/voice/* client, the guide and the three tools
  prompts.py      system prompt assembled at runtime
  audio.py        microphone, RMS, end-of-speech detector
  devices.py      which microphone and which speaker, chosen by name
  speech.py       faster-whisper and piper behind two methods
  i18n.py         all interface and voice text, in Spanish and English
  config.py       JSON settings with environment overrides
  originality.py  prose and code comparison against another tree
  ui/             Qt window and an orb drawn with QPainter
```

Decisions worth knowing:

- **End of speech by energy, not by the clock.** The threshold adapts to the
  background noise only while nobody is speaking, so a fan that starts
  mid-sentence does not swallow the end. It is tested with synthetic frames, no
  microphone needed.
- **A tool timeout does not freeze the conversation.** Both synchronous and
  asynchronous tools are cut off in time and the model gets a sentence.
- **No SDK.** A `urllib` call with an explicit `timeout` avoids pinning client
  versions and lets the same code point at a local test server.
- **The guide is shown and spoken with the same text**, so the voice promises
  nothing the screen does not say.
- **Audio devices are saved by name, not by number.** PortAudio's indices change
  when something is plugged in, so they are resolved when the stream opens; if
  the chosen one disappeared it falls back to the default, without an error.

## Tests

```bash
pytest -q          # 187 tests
```

They cover the end-of-speech detector with synthetic signals, the tool registry
(types, made-up arguments, exceptions, timeouts), the factory client **against a
real HTTP server**, a full end-to-end turn with a model server and a factory
server (pick a tool, come back with the result, answer), the choice of
microphone and speaker (with a fake device table that mimics PortAudio), the
output voice in both languages (the command that would run on each system, the
fallback when the engine does not play), the security rules above and the
originality comparison.

## Third-party licenses

`PyQt6` (GPL-3.0 or Qt's commercial license), `sounddevice` (MIT), `numpy`
(BSD-3), `faster-whisper` (MIT), `piper` (MIT). The details are in `NOTICE`.
If you are going to distribute the binary with PyQt6, check that license: it is
the only one in the set that is not permissive.

This package: Apache-2.0. See `LICENSE`.
