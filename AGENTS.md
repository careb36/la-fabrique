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

Windows (what the user actually runs):

```powershell
.\arrancar.cmd                       # doble clic también sirve
.\arrancar.ps1 -Puerto 8100          # backend + asistente en otro puerto
.\arrancar.ps1 -Instalar             # primera vez: crea venvs e instala
.\arrancar.ps1 -SoloBackend          # sin GUI (servidor, pruebas)
.\arrancar.ps1 -Reinstalar           # rehace los venvs
```

Linux/macOS:

```bash
python run_fusion.py

# backend only, no infra: SQLite + NEO4J_DISABLED + NATS_DISABLED
python run_fusion.py --backend-only --port 8126 --voice-key k

# backend tests (no Postgres/NATS/LLM). Needs PYTHONPATH=.:app
cd la-fabrique/backend && PYTHONPATH=.:app ../../.venv-backend/bin/python -m pytest tests -q

# assistant plugin tests (no Qt, no audio)
cd profesor3 && PYTHONPATH=. ../../.venv-backend/bin/python -m pytest tests -q

# launcher tests (run_fusion + lock exporter)
.venv-backend/bin/python -m pytest tests -q

# check the launcher parses under PowerShell (no Windows needed)
pwsh -NoProfile -Command '$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("$PWD/arrancar.ps1",[ref]$t,[ref]$e);$e'

# what the pip fallback would install from the lock
python tools/lock_requirements.py la-fabrique/backend/poetry.lock --groups main
```

`arrancar.ps1` is UTF-8 **with BOM** and `arrancar.cmd` is CRLF: Windows
PowerShell 5.1 mangles accents otherwise. Keep both properties when editing.
Running the `.ps1` under PowerShell 7 on Linux needs
`DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` (no ICU in the container).

Full backend suite ≈ 50 s / 745 tests; a fresh server boot takes 40+ s in a
slow container because importing `agents.graph` is heavy — raise `--wait` if
`run_fusion.py` gives up too early.

## Gotchas

* The backend imports both `app.*` and top-level modules, so it needs
  `PYTHONPATH=<backend>:<backend>/app` (the launcher sets it, mirroring the
  Dockerfile).
* Port 8000 may be taken by something else; the launcher identifies the
  factory by `/v1/capabilities`, never by `/health`. `arrancar.ps1` probes for
  a free port and tells the user to pass `-Puerto`.
* `NEO4J_DISABLED=true` and `NATS_DISABLED=true` make the graph and the broker
  optional: endpoints degrade instead of failing and the console stops printing
  a reconnect traceback every few seconds. `run_fusion.py` sets both for local
  installs; `docker compose up -d` in `la-fabrique/` brings the real ones back.
* Poetry must be told to reuse the venv the script created:
  `VIRTUAL_ENV=<venv>` + `POETRY_VIRTUALENVS_CREATE=false`, otherwise it makes
  its own and the launcher finds an empty interpreter.
* Poetry can fail on Windows with "All attempts to connect to pypi.org failed"
  while pip and `Invoke-WebRequest` work: Poetry only trusts certifi, pip and
  Windows use the machine's root store (TLS-inspecting antivirus/proxy). The
  launcher exports the store to `logs/windows-ca-bundle.pem` and sets
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` — never disable verification. If that
  still fails it installs with pip from `tools/lock_requirements.py`, which
  keeps the exact `poetry.lock` pins (markers and groups respected).
* Never let PowerShell 5.1 handle Python's stderr through the pipeline: with
  `$ErrorActionPreference='Stop'` a native command's stderr becomes a
  `NativeCommandError` and aborts mid-install. The launcher keeps
  `Continue` and runs probes through `Start-Process` with redirected streams.
* Venv layout is platform-specific: Windows has `Scripts\python.exe`, POSIX has
  `bin/python`. Both `arrancar.ps1` and `run_fusion._venv_layout()` filter by
  `os.name`; a `bin/python` path on Windows makes cmd.exe report "no se puede
  ejecutar un documento en medio de una canalización".
* The interpreter is only accepted after it actually runs (`-c import sys` or
  the info probe): an empty `Scripts\python.exe` or the Windows Store stub
  (exit 9009) must be ignored, not used.
* `py -3.12` needs its prefix passed through, otherwise `py` resolves to
  whatever version is default (3.14 here) — `Get-PythonInfo` and `New-Venv`
  take the candidate's `Prefix`.
* Never trust one way of finding Python. `Find-SystemPython` merges
  `py --list-paths`, the registry (`PythonCore\<ver>\InstallPath`), `Python3*`
  folders under `%LOCALAPPDATA%\Programs\Python`, `Program Files` and `C:\`,
  the `home` recorded in each venv's `pyvenv.cfg`, and the PATH — then probes
  each candidate. A machine where `py` is missing but Python 3.12 lives in
  `AppData\Local\Programs\Python\Python312` is the normal case, not the edge.
* `Start-Process ... -RedirectStandardOutput` needs a second
  `$process.WaitForExit()` (no timeout) before reading the file: .NET's async
  readers may not have flushed yet, the file reads empty and every interpreter
  looks unusable. `Invoke-Python` also retries in-process
  (`Invoke-PythonInProcess`) when nothing was captured, and if a probe still
  fails it accepts the path that `pyvenv.cfg`/the registry declare — with a
  loud warning instead of aborting.
* `$home` is a read-only automatic variable in PowerShell: naming a local
  `$home` throws "Cannot overwrite variable HOME". Use `$baseHome`.
* A `pyvenv.cfg` copied from another OS points at a `home` that does not exist
  here; `Test-Path 'C:\...'` on Linux raises "Cannot find drive" and pollutes
  the output. Wrap the reachability check in `try/catch`.
* `.\arrancar.ps1 -Diagnostico` is the support tool: it lists every candidate,
  its version, its source, each probe result, and which interpreter would be
  used, without installing anything. Keep it working and in the README table.
* Broken environments are moved to `<venv>.roto-<timestamp>`, never deleted:
  `-Reinstalar` is explicit and the backup is the user's safety net.
* `logs/` holds the transcript, the exported CA bundle and the generated
  requirements; it is git-ignored. `pip check` warnings are reported but do not
  stop the launch.
* Sprint creation by voice is always followed by a pause: an explicit "reanuda"
  is required before agents get any work.
* Voice vocabulary is duplicated on purpose: `plugins/fabrica.py` (`ACTIONS`,
  the model-facing enum) and `voice_control.VOICE_ACTIONS` (canonical names +
  paraphrases). Add an action to both, plus `_HANDLERS` in `voice.py`.
