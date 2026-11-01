# Speech service

The server tier of the voice layer: the best recognizer and the best voice
the project has, behind two routes, for any client with a backend at hand
(La Fabrique XR in live mode, OSINT Orchestrator, the desktop assistant).
The device tier (Whisper and Piper in the page) needs none of this; this
is what a page uses when it can, because faster-whisper `large-v3-turbo`
hears Spanish far better than a model that fits in a headset, and Kokoro
sounds like a person.

| Route | In | Out |
| --- | --- | --- |
| `POST /v1/transcribe?languages=es,en&preferred=es&prompt=...` | 16-bit PCM WAV (any rate) | `{text, language, seconds}` |
| `POST /v1/speak` | `{text, language, voice?}` | `audio/wav` (Kokoro, 24 kHz) |
| `GET /health[?warm=1]` | | both engines described; `warm` loads them |

The language is detected among the ones the client speaks, and the page's
language (`preferred`) wins a close call; `prompt` is the client's
vocabulary, Whisper's previous text, which steers the decoding toward the
commands. Kokoro's voices: `ef_dora` for Spanish, `af_heart` for English,
or any voice of the model by name.

## Running

```bash
docker compose --profile speech up -d speech     # port 5200
# or, with the models downloaded by hand:
pip install -r speech-service/requirements.txt
SPEECH_KOKORO_DIR=~/.b1/kokoro python speech-service/models.py   # fetches Kokoro, checks the hashes
SPEECH_KOKORO_DIR=~/.b1/kokoro python speech-service/app.py
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPEECH_API_KEY` | unset | When set, `/v1/*` need it in `X-API-Key`. |
| `SPEECH_CORS_ORIGINS` | unset | Comma-separated pages allowed to call from a browser. |
| `SPEECH_STT_MODEL` | `large-v3-turbo` | Any faster-whisper model (`small` for a slow CPU). |
| `SPEECH_DEVICE` / `SPEECH_COMPUTE_TYPE` | `cpu` / `int8` | `cuda` / `float16` on a GPU. |
| `SPEECH_KOKORO_DIR` | `/models/kokoro` | Kokoro's two files (pinned SHA-256 in `models.py`). |

The first transcript downloads the recognizer's model (about 1.6 GB for
`large-v3-turbo`); `GET /health?warm=1` does it ahead of time.

## Tests

```bash
pip install -r speech-service/requirements-dev.txt fastapi numpy
python -m pytest speech-service/tests -q
```

The API is tested with stand-in engines; no model is needed.
