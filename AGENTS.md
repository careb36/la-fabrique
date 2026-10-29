# AGENTS.md — fusión La Fabrique + MARK LVI

## Layout

* `run_fusion.py` — the only entry point. Starts the backend (uvicorn) and the
  desktop assistant, shares `VOICE_API_KEY` between them, bootstraps the first
  company and writes the URL/key into `profesor3/config/api_keys.json`.
* `la-fabrique/` — upstream checkout (`le-fabrique-backend`; FastAPI + SQLModel).
  Voice façade: `backend/app/routers/voice.py` +
  `backend/app/services/voice_control.py`. It only calls the same router
  functions the web UI uses, so voice cannot bypass validation.
* `profesor3/` — upstream checkout (MARK LVI assistant, PyQt6 + Gemini Live).
  The fusion lives in `plugins/fabrica.py`, auto-discovered by
  `core/plugin_loader.py` (contract: `PLUGIN`, `PLUGIN_SETTINGS`, `run()`).
* `tests/test_run_fusion.py` — launcher tests (real HTTP stubs, no mocks).

Both subdirectories are **separate git checkouts** and are gitignored here;
commit changes in their own repos.

## Environment

* Backend deps: `.venv-backend/` (Python 3.13). `sqlmodel` must stay at
  `0.0.38`; 0.0.48 breaks the voice tests.
* Assistant deps: `profesor3/.venv/` (needs `PyQt6`, `google-genai`).
* `run_fusion.py` auto-detects both interpreters; override with
  `--backend-python` / `--assistant-python`.

## Commands

```bash
# whole product (backend + assistant)
python run_fusion.py

# backend only, no infra: SQLite + NEO4J_DISABLED
python run_fusion.py --backend-only --url http://127.0.0.1:8126 --voice-key k

# backend tests (no Postgres/NATS/LLM). Needs PYTHONPATH=.:app
cd la-fabrique/backend && PYTHONPATH=.:app ../../.venv-backend/bin/python -m pytest tests -q

# assistant plugin tests (no Qt, no audio)
cd profesor3 && python -m unittest discover -s tests -q

# launcher tests
.venv-backend/bin/python -m pytest tests -q
```

Full backend suite ≈ 2 min / ~744 tests; a fresh server boot takes 40+ s in a
slow container because importing `agents.graph` is heavy — raise `--wait` if
`run_fusion.py` gives up too early.

## Gotchas

* The backend imports both `app.*` and top-level modules, so it needs
  `PYTHONPATH=<backend>:<backend>/app` (the launcher sets it, mirroring the
  Dockerfile).
* Port 8000 may be taken by something else; the launcher identifies the
  factory by `/v1/capabilities`, never by `/health`.
* `NEO4J_DISABLED=true` makes graph endpoints degrade instead of failing.
* Sprint creation by voice is always followed by a pause: an explicit "reanuda"
  is required before agents get any work.
