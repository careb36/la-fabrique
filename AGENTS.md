# AGENTS.md — fusión La Fabrique + Asistente B1

## Layout

* `run_fusion.py` — the only entry point. Starts the backend (uvicorn) and the
  desktop assistant, shares `VOICE_API_KEY` between them, bootstraps the first
  company and writes the URL/key into the chosen assistant's config
  (`asistente-b1`: `~/.asistente-b1/config.json`; `profesor3`:
  `config/api_keys.json`). `--asistente {b1,profesor3}` picks the front end;
  **b1 is the default and the product that ships**.
* `asistente-b1/` — the assistant written for this repository, Apache-2.0.
  Own package (`b1/`), own tests (`pytest -q` → 104), no dependency on
  `profesor3/`. Runs as `python -m b1` from inside the folder.
* `la-fabrique/` — upstream checkout (`le-fabrique-backend`; FastAPI + SQLModel).
  Voice façade: `backend/app/routers/voice.py` +
  `backend/app/services/voice_control.py`. It only calls the same router
  functions the web UI uses, so voice cannot bypass validation.
* `profesor3/` — upstream checkout (PyQt6 + Gemini Live), CC BY-NC 4.0: kept as
  reference and as the `--asistente profesor3` front end. Do **not** copy code
  or copy from it into `asistente-b1/`: `tests/test_originality.py` fails.
  The fusion lives in `plugins/fabrica.py`, auto-discovered by
  `core/plugin_loader.py` (contract: `PLUGIN`, `PLUGIN_SETTINGS`, `run()`).
* `agentes/` — the workspace the factory's agents write into when started with
  `--completa` / `-Completa`. Contents are gitignored except `LEEME.md`.
* `builds/` — where a chat sentence becomes a real project (`POST
  /v1/voice/build`). Generated, gitignored; the Python files live in
  `la-fabrique/backend/app/{services/codegen.py,routers/build.py}`.
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

## Modo fábrica completa

`--completa` / `-Completa` is the only path where agents actually execute:
`docker compose up -d postgres nats llm-proxy` (cwd `la-fabrique/`), secrets
filled into `la-fabrique/.env`, backend pointed at `127.0.0.1` (never at the
compose service names, which do not resolve from the host), and
`vscode-daemon` started natively with `WORKSPACE_ROOT=<agentes>` (also
under `--backend-only`, so a headless server still executes).

`AGENT_MODEL` overrides every role at once, and the launcher sets it in both
modes: `_agent_model()` picks the id the installed keys can actually serve
(NVIDIA → `nvidia/nemotron-3-ultra-…`, only Gemini → `gemini-flash-latest`).
Without it the role map's Qwen/DeepSeek ids come back from the proxy as
"unknown model" and tasks end blocked. `ModelFactory.model_for_role` is the
single resolver: `default_model_for_role` and `agents/graph.py` both go
through it.

### El proxy de modelos no depende de Docker

In local mode (`run_fusion.py` without `--completa`) the launcher runs
`la-fabrique/llm-proxy/app.py` with the backend interpreter
(`PROXY_HOST=127.0.0.1`, log at `la-fabrique/.fusion/llm-proxy.log`) whenever
`la-fabrique/.env` carries a provider key and nobody answers on `/v1/models`.
Without it every request ended in "No pude hablar con el proxy de modelos":
agents and `POST /v1/voice/build` have no other route to a provider. The process
stops with the rest of the stack.

* The check is `GET /v1/models` **with** models, never the port alone: Docker
  keeps `5100` published after the process inside dies, and that case is now
  reported with the tail of `docker compose logs llm-proxy`.
* With no provider key the launcher says so at start-up instead of letting the
  first sentence fail.
* The interpreter comes from `la-fabrique/llm-proxy/.venv` when nothing else can
  import Flask (`.venv-backend` cannot: the proxy is a separate Poetry project).
  The launcher builds it from `llm-proxy/poetry.lock` on the first start, which
  takes a couple of minutes once.
* `LLM_PROXY_TIMEOUT_SECONDS` (150 s) has to outlast the proxy's own upstream
  budget (`LLM_UPSTREAM_TIMEOUT_SECONDS`, 110 s). It used to be 60 s with two
  retries, so the proxy "went down" while it was still writing the files, and a
  read timeout is no longer retried.
* Codegen sends `chat_template_kwargs.enable_thinking=false` to `nvidia/*` ids:
  reasoning before writing doubled the time for a whole-file answer.

Verified end to end in this repo without Docker (the sandbox cannot mount
overlayfs): native `nats-server -js` + PostgreSQL 17 + the proxy + backend with
the same env `--completa` exports, then voice → sprint → dispatch → agent →
`agentes/` files (`src/`, `tests/`, `README.md` written by a Gemini-backed
Developer agent).

Full backend suite ≈ 50 s / 745 tests; a fresh server boot takes 40+ s in a
slow container because importing `agents.graph` is heavy — raise `--wait` if
`run_fusion.py` gives up too early.

## De una frase a un proyecto servido

`plugins/fabrica.py` reconoce el pedido (`looks_like_build_request`,
`clean_build_request`) y llama a `POST /v1/voice/build`; el endpoint no pasa por
el grafo LangGraph a propósito: es una acción de un solo turno y la persona está
esperando el resultado.

* El generador (`services/codegen.py`) es puro y se prueba con un `chat`
  inyectable: `build(root, texto, chat)`. Escribe sólo rutas relativas seguras,
  nombra el slug con fecha (dos pedidos en el mismo segundo no se pisan) y
  devuelve `files/entry/preview/seconds`.
* `MAX_ANSWER_TOKENS` (8192) se manda como `max_tokens` al proxy: las respuestas
  cortadas a mitad de JSON son la causa más común de «el modelo no devolvió
  archivos». Si el parseo falla se reintenta **una** vez pidiendo sólo el JSON.
* `_candidate_models()` prueba el id del rol Developer, después
  `NEMOTRON_MODEL_STRATEGIC` y después el default del mapa de roles: el catálogo
  del proveedor cambia y un id ausente no puede costar la función entera.
* `GET /v1/voice/build/<slug>/<archivo>` sirve con `sandbox` + CSP propio. Ojo:
  `SecurityHeadersMiddleware` es el middleware más externo y **ahora respeta** el
  `Content-Security-Policy` que ya trae la respuesta (si lo pisara, el sandbox
  desaparecía sin que ningún test de endpoints lo notara).

## Asistente B1 (`asistente-b1/`)

The clean-room assistant: standard library for the core (model client, tools,
conversation loop, end-of-speech detection), PyQt6 for the window, and optional
faster-whisper / piper / sounddevice for voice. Without them it still starts —
as a console — and says what is missing.

```bash
cd asistente-b1
python -m b1 --check     # inventory + live probe of model and factory
python -m b1 --text      # console turn loop
pytest -q                # 150 tests, no network, no microphone
python tools/similarity_check.py ../profesor3   # must print 0 / 0
```

Invariants worth keeping:

* **The factory writes the words.** `/v1/voice/*` returns `speech` already
  phrased for speaking; the assistant repeats it instead of inventing numbers.
  A tool failure returns `{"ok": false, "speech": "..."}`, never an exception
  into the loop.
* **No SDKs.** `b1/llm.py` is `urllib` with explicit timeouts, which is what
  lets `tests/test_end_to_end.py` run a real model server on localhost.
* **Prose is part of the diff.** The prompt, the guide and every user-facing
  sentence live in `b1/prompts.py` and `b1/fabrica.py`; `originality.py`
  compares both prose (8-word sequences) and code (14-token sequences).
* **`Settings.missing()`** ignores the API key for loopback model URLs, so the
  factory's `llm-proxy` (`http://127.0.0.1:5100/v1`, no auth) works out of the
  box with `--completa`.
* **Two languages, one program.** `b1/i18n.py` holds every user-facing string
  as `{"es": ..., "en": ...}` and `t(language, key, **fields)`; nothing is
  translated on the fly. `prompts.py` has a Spanish and an English prompt
  written separately (a translated prompt makes the model answer like one),
  `fabrica.py` switches tool descriptions, and `/v1/voice/*` calls carry
  `language` so the factory's own `speech` arrives in the right one. The
  conversation switches language when the *phrase* does: `detect_language()`
  uses Spanish/English function-word hints and only falls back to the
  transcriber's guess on a tie. `MainWindow._on_language` re-labels the window
  in the same turn. `stt_language` is `auto` (follow the conversation) or a pin.
* **The voice chain is Piper → system voice → console.** `speech.py` builds the
  script each engine would run (`-EncodedCommand` + base64 UTF-16LE for SAPI,
  `say -v`, `espeak-ng -v`, `spd-say -l`) so tests read it without hardware. A
  missing model or engine falls through silently-but-reported; an engine that
  exits 0 **while printing an audio error** (espeak with no sound card) is
  detected from stderr and the sentence goes to the console plus one line of
  reason. `b1 --voices` downloads the configured Piper voices (they ship
  separately) into `~/.asistente-b1/voces`, using the interpreter that owns
  `piper-tts` — not necessarily the assistant's own.
* **Audio devices are saved by name.** `b1/devices.py` lists each endpoint
  once (aliases such as `default` / "Sound Mapper" are dropped, inputs that
  cannot run at 16 kHz are dropped), caches the list, and resolves the saved
  name to an index every time a stream opens — a headset that is gone falls
  back to the system default. The dialog has "Probar micrófono" (3 s with a
  live level bar) and "Probar parlante" (a beep); both run on a `QThread`.
* **Nemotron's reasoning is never spoken.** `Reply.reasoning` keeps
  `reasoning_content` for the log; `chat_template_kwargs.enable_thinking` is
  only sent to endpoints that serve that family (`nemotron` in the id, the
  NVIDIA gateway or Token Factory), because a strict server rejects an unknown
  field. Tuning lives in `config.json`: `model_thinking`, `model_temperature`,
  `model_top_p`, `model_max_tokens`, `model_timeout`.
* **Default model** is `nvidia/nemotron-3-ultra-550b-a55b` served by
  `https://integrate.api.nvidia.com/v1` with an `nvapi-…` key; the launcher
  copies that key from `la-fabrique/.env` (or `NVIDIA_API_KEY`) into
  `~/.asistente-b1/config.json` when there is no proxy in front. The proxy
  refuses `stream: true` (`400 stream_unsupported`) because it relays one body.

Live check of the real contract (Linux; `.venv-backend/` is a Windows venv):

```bash
cd la-fabrique/backend
DATABASE_URL=sqlite:////tmp/f.db AUTH_REQUIRED=false NEO4J_DISABLED=1 \
NATS_DISABLED=1 VOICE_API_KEY=clave-demo SECRET_KEY=x JWT_SECRET_KEY=y \
PYTHONPATH=.:app python -m uvicorn app.main:app --port 8137
# then: POST /v1/init_company with {"company_name", "agents": [...]}
# and:  curl /v1/voice/status -H 'X-Voice-Key: clave-demo'
```

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
  its version, its source, each probe result, which interpreter would be used
  and the network verdict (DNS, HTTPS to pypi, a real `pip download`, proxy
  variables), without installing anything. Keep it working and in the README.
* Installing needs PyPI. When poetry and pip both fail,
  `Show-NetworkDiagnosis` explains why (DNS vs TLS vs proxy) and
  `Copy-MissingModulesFrom` borrows the pure-Python wheels the backend shares
  with the assistant env (httpx, httpcore, distro, sniffio, anyio, h11,
  annotated_types, typing_extensions) so the factory still boots offline. The
  copy never overwrites and skips anything with `.pyd`/`.so`; the launcher
  warns that it is provisional and `-Instalar` fixes it with the network.
  Locate site-packages with `Get-SitePackages` (Lib\site-packages on Windows,
  lib/pythonX.Y/site-packages elsewhere).
* Broken environments are moved to `<venv>.roto-<timestamp>`, never deleted:
  `-Reinstalar` is explicit and the backup is the user's safety net.
* `logs/` holds the transcript, the exported CA bundle and the generated
  requirements; it is git-ignored. `pip check` warnings are reported but do not
  stop the launch.
* The SQLite build (the desktop one) rejects Postgres-only SQL, and the outbox
  worker used two such constructs: `FOR UPDATE SKIP LOCKED` in the poll and
  `NOW()` in the two UPDATEs. Both are now portable (`database.IS_SQLITE`
  drops the locking clause; `processed_at` gets a bound
  `datetime.utcnow()`). Symptom if they come back: `Outbox processor error:
  ... near "FOR"` / `no such function: NOW` every two seconds and **nothing
  ever reaching the agents**, while `/v1/voice/*` still answers 200.
* Sprint creation by voice is always followed by a pause: an explicit "reanuda"
  is required before agents get any work.
* Voice vocabulary is duplicated on purpose: `profesor3/plugins/fabrica.py`
  (`ACTIONS`, the model-facing enum) and
  `la-fabrique/backend/app/services/voice_control.py` (`VOICE_ACTIONS`,
  canonical names plus Spanish/English paraphrases, resolved in
  `routers/voice.py`). Add an action to both or the voice gets a 400. `abrir`
  is the exception: the assistant handles it locally — it asks the Qt
  window to bring the in-app board up (see *Panel de la fábrica en Qt*) and
  only falls back to `webbrowser` when no UI registered the hook.

## El tablero dentro del asistente

* The factory tab is the factory's **own** React UI, embedded — not a copy. `GET /fabrica` is a doorway: it asks `/v1/auth/desktop` for a session with the assistant's own key and redirects to the backend with `#sesion=<token>` in the fragment, which never reaches a server or a log. The old `dashboard/static/fabrica.html` (a hand-written imitation) is gone; `tests/test_dashboard_panel.py` fails if it comes back.
* Embedding crosses origins, so the factory's `frame-ancestors` must name the panel. `run_fusion.py` sets `FRAME_ANCESTORS` to loopback with a wildcard port (`http://127.0.0.1:*`, `http://localhost:*`, both schemes) because the panel moves to the next free port when 8770 is taken; without it `X-Frame-Options: DENY` blanked the tab. The headers are attached *after* `mount_ui` (`security.add_security_headers`) so the SPA shell — the page an iframe actually loads — carries them too.
* The page never talks to the factory directly. `dashboard/server.py` proxies `/api/fabrica/status` and `/api/fabrica/command` to `/v1/voice/*` with `X-Voice-Key`, so the shared key stays out of the browser and the buttons use exactly the voice vocabulary. Keep the two lists in step.
* `run_fusion.py` opens the **assistant's panel** first — that is where the new identity lives and the factory is one tab inside it. `_panel_answers()` probes `http://127.0.0.1:8770/health`, which answers `{"app": "tutor-virtual-a1"}`, so a stranger holding the port is never mistaken for us; after `PANEL_WAIT_SECONDS` without an answer the launcher falls back to the factory UI with `#sesion=…` (still polled, because the backend starts before the UI is reachable). `--no-browser` / `-SinNavegador` turn it off.
* The panel asks for no pairing key on the machine that runs the assistant: `GET /` bakes `__LOCAL_TOKEN__` (`DashboardServer.local_session()`) into the page **only** when the request is loopback (`_is_local`), and `_valid` accepts that token. Everything off loopback still types the key from *Remote control* — a paired device never receives the local token, and it dies with the process (a restart mints a new one, and the freshly served page carries it). The token has no pairing key, so the page skips the AES layer locally: that layer only ever mattered on a network.
* The panel only works signed in: `/` and `/login` want the 8-character pairing key the desktop shows under *Remote control*. `/api/fabrica/*` and `/fabrica` are exempt for loopback (`_panel_allowed`), which is why the desktop page can embed the factory with a `?token=` query.
* Navigation was trimmed to the factory on purpose: the browser rail drops Nucleo/Profesor/Clase/Curso/Pizarra and `ui.py` hides those rail buttons plus the phone and call buttons in the header. The views still work by voice and by shortcut; `tests/test_dashboard_views.py` pins the removals.
* `arrancar.ps1` must stay UTF-8 with BOM and CRLF; writing it with plain `Path.write_text` silently breaks `tests/test_launcher_script.py`. Rewrite it as `b"\\xef\\xbb\\xbf" + text.replace("\n", "\r\n").encode("utf-8")`.
* FastAPI needs `python-multipart` even when only `/v1/voice/*` uses JSON: the login form is declared at import time. A bare venv without it fails at startup, not at request time.
* The React app is `la-fabrique/frontend`, a sibling of `la-fabrique/backend` — the backend serves it from `frontend/dist` (`app/ui_static.dist_dir`). `Install-Frontend` in `arrancar.ps1` used to point npm at `<backend>/frontend`: `Push-Location` failed, npm looked for `package.json` in the repo root and the whole launch aborted with ENOENT. It is now opt-in (`-InterfazWeb`), because a first launch must never wait on npm. Keep it warning-only: the API and the voice do not need the SPA, and the backend already answers `/` with a page explaining the missing build.

## Panel de la fábrica en Qt (`profesor3/ui_fabrica.py`)

* The board lives **inside** the assistant: the *Fábrica* button, the factory
  card, the orb menu (*Generar con la fábrica*) and the spoken «abrí la
  fábrica» all end up in `MainWindow._open_factory_panel()`. The browser tab
  (`dashboard` → `#/fabrica`) is still one click away from the panel's header.
* Voice → UI goes through a signal, never a direct call: the plugin runs in a
  worker thread, so `MainWindow._register_factory_hook()` hands
  `plugins.fabrica.open_panel_hook` a callable that emits `_fabrica_open_sig`
  and returns `True`. Without the hook (CLI, tests, headless) the plugin keeps
  the old `webbrowser` path.
* Every HTTP call runs off the UI thread (`_start`), and the chain stops at the
  first failure — a half-created sprint is reported as such, never as success.
* *Generar* runs the same four steps the voice runs, in that order:
  `planear` → `crear_sprint` (born **paused**) → `reanudar` → `despachar`.
  Keep it that way: `despachar` on a paused sprint is a 400 by design.
* The panel reads `counts` (todo/in_progress/in_review/done/blocked),
  `sprint.{id,name,status}`, `company.name` and `pending_approvals` straight
  from `/v1/voice/status` — the payload `voice_control.status_snapshot`
  returns. If that shape changes, `tests/test_dashboard_fabrica.py` and the
  panel both need the new key.
* `AI-Workspace.exe --floating` (or `profesor3\boton-flotante.cmd`) boots
  straight into the desktop orb: `main()` calls `MainWindow.start_floating()`
  so the window is never shown and hidden.

## Panel web («Identidad 2.0 · Consola»)

* `dashboard/static/app.html` (one file, no build) carries the same identity as
  the desktop: graphite surfaces (`--bg #08090D`), one signal orange, hairlines,
  radii 4–14px. Navigation lives in a **top bar**, utilities (idioma, tema,
  estado, inspector) in a **drawer** behind ☰, the inspector **slides over** the
  content, and the view title moved to the **footer status bar**. Ids and body
  states (`sidebar-open`, `inspector-open`) are the originals, so the script did
  not need rewriting.
* `tests/test_dashboard_panel.py` guards the split: every `getElementById` in the
  script must exist in the markup (`core-visual` is the documented exception),
  the nav must hold its four tabs, the drawer must stay outside `.main`, the
  inspector must not branch on `innerWidth`, and the Fábrica tab must set
  `frame.src = '/fabrica'`.
* `profesor3/dist/AI-Workspace.exe` is a *frozen copy of the code*: a build older
  than `ui.py` or `dashboard/static` shows the previous skin, which is what "the
  exe still looks old" meant. `tools/build_exe.py --check` reports it (0 up to
  date, 1 no build, 2 stale), `arrancar.ps1` warns on every start, and
  `regenerar-ejecutable.cmd` / `-Recompilar` / `-SoloCompilar` rebuild it.
  `.rrancar.cmd` itself always runs from source, so a stale exe never changes
  what the launcher shows — only what the user sees if they open the exe.
  PyInstaller cannot cross-compile: the Windows exe is built on Windows —
  the Linux sandbox can only prove the spec packages the new assets
  (`_internal/dashboard/static/app.html` → CONSOLA). `clear_build_outputs()`
  removes only `dist/AI-Workspace*` and `build/`, never the `config/`,
  `memory/`, `logs/`, `plugins/` the exe writes beside itself.
* The user's Windows box has a **second, older copy** of the app at
  `C:\Users\Felipe\projects\profesor3` (ui.py of 28-oct) with its own
  `dist\AI-Workspace.exe`; the shortcut opened that one, which is why the
  old face kept coming back. `dist\logs\ai-workspace.log` names the exact
  binary that ran (`python=3.12.10 exe=…`) — check it before rebuilding.
  `/projects` here is the Windows `C:\Users\Felipe\projects` share, so the
  files are shared even though the sandbox is Linux (no cmd.exe, no Wine).
* The desktop header (ui.py, `PROFESOR` / `Intelligent Workspace` labels) uses
  the same wordmark as the panel: **CONSOLA** / *asistente de fábrica*.
* The panel calls itself **CONSOLA** — `<title>`, `.brand-name` and `.brand-tag`,
  in both languages; `login.html` says «CONSOLA · acceso remoto». The first pass
  of the redesign left the old brand and its gradients in place, which is why a
  launch still looked old: `rgba(233,200,151,…)` (champagne), `#9CA1E2`/`#BAA9B7`
  (indigo mark) and the gradients on the brand mark, the primary button and the
  active tab are gone. Grep for those literals before adding a surface.
* The theme switch used to be a no-op in the browser (it only told the desktop
  assistant). `applyTheme()` now sets `data-theme` on `<html>`, remembers the
  choice in `localStorage.jarvis_theme`, and `:root[data-theme="light"]`
  redefines the same token names — light mode is a palette swap, nothing else.

## Diseño del escritorio («Consola»)

* The assistant's look is now its own: graphite surfaces, one signal orange
  (`#FF6A45` dark / `#C2410C` light), ice blue for secondary state and lime for
  "live". Flat chrome, 1px hairlines, radii from 4 to 14px, body type one point
  larger than the old skin. `ui.THEMES` remains the single source of truth and
  `profesor3/tests/test_palette.py` enforces the WCAG floors.
* The previous skin was indigo + champagne/copper, and its light theme was
  cream. Do not reintroduce amber/gold tokens, vertical gradients on the
  sidebar or the header, or 20px+ bubble corners: each of those was removed on
  purpose, and `profesor3/tools/ui_check.py` regenerates the screenshots under
  `profesor3/screenshots/v2/` so a regression is visible.
* `docs/rediseno/index.html` is the visual summary (dark, light, conversation,
  núcleo) — open it before proposing a colour or radius change.
* The web app (`la-fabrique/frontend`) still carries the indigo brand palette.
  Harmonising the two means porting this structure (flat surfaces, hairlines,
  tight radii, mono micro-labels) to Tailwind and swapping indigo for the
  signal orange — it is not done yet.

## Barra lateral, círculo flotante y estado de la fábrica

* La barra lateral tiene cuatro zonas fijas, en este orden: marca (logo +
  **CONSOLA** / *asistente de fábrica* + «+» de chat nuevo), navegación
  (`Asistente`, `Fábrica`, `Nemotron`, `Agentes`), **tarjeta de la fábrica** y,
  al pie, sesión, idioma, tema y el *dock* de utilidades (`Controles`,
  `Ajustes`, `Flotante`, `Contraer`). `Núcleo`, `Profesor`, `Clase`, `Curso`,
  `Pizarra` y `Móvil` siguen existiendo pero ocultas: se abren por voz o por
  atajo, no por clic.
* La ventana está **espejada** (`_MIRRORED = True` en `ui.py`): la navegación
  queda a la derecha y el inspector a la izquierda. El orden se invierte en un
  solo sitio —`_build`, `_build_header` (con `_reverse_row`) y `_place_drawer`—
  así que un widget nuevo sólo tiene que añadirse al *layout* normal y no
  calcular coordenadas propias. Volver al diseño original es poner el flag en
  `False`.
* La tarjeta de la fábrica es información viva: `_refresh_factory_state`
  pregunta a `/v1/voice/status` en un hilo y vuelve por `_factory_state_sig`
  (nunca bloquea el hilo gráfico), se repinta cada 30 s y tiñe el punto de
  verde o rojo. Un clic abre el tablero con el mismo pre-vuelo que usa la voz.
* El *dock* se reordena solo: fila de cuatro iconos con la barra ancha, columna
  con la barra contraída (`_layout_dock`). Si añades un botón al dock, mételo en
  esa tupla o quedará fuera del ancho de 76 px.
* `FloatingOrb` (96×96, sin marco, siempre encima) sustituye a la ventana
  cuando el modo flotante está activo: clic devuelve la consola, arrastrar lo
  mueve, clic derecho abre el menú, y la posición se guarda al soltar
  (`floating_orb_pos` en `config/api_keys.json`). Con el modo activo,
  `closeEvent` **oculta** en vez de cerrar; `_quitting = True` es la única vía
  de salida real.
* `dashboard/server.py::_factory_down_page` es lo que se ve en `/fabrica`
  cuando el backend no responde: dirección, motivo (HTTP o excepción) y el
  comando de uvicorn. No se redirige nunca a un puerto muerto.

## Hablarle a los agentes y la clave de Nemotron

* `plugins/fabrica.py` tiene una acción más: `asignar`. Convierte una frase
  dictada en una `BacklogItem` a nombre de un agente y emite el mismo evento
  `task.assign` que usa el tablero web
  (`la-fabrique/backend/app/routers/voice.py::_action_assign`). Si el sprint
  está en pausa la tarjeta se crea pero no se despacha: reanudar sigue siendo
  decisión de la persona. El agente se busca por id, nombre exacto o
  coincidencia única en nombre/rol (`voice_control.find_agent`); si no hay
  coincidencia, la respuesta enumera el equipo en vez de adivinar.
* El panel **Agentes** (`ui_agentes.py`) lista el equipo real
  (`plugins.fabrica.list_agents()` → `/v1/voice/command` `equipo`). Al elegir
  uno, `set_active_agent()` lo deja como destino por defecto y el compositor
  queda con el prefijo «Decile a <nombre> que »: si el modelo no nombra agente,
  el plugin rellena el que está elegido (un nombre dicho en voz alta siempre
  gana). El estado vive en el módulo del plugin, no en el panel.
* El panel **Nemotron** (`ui_modelos.py` + `core/fabrica_env.py`) escribe
  `NEBIUS_API_KEY`, `NEBIUS_PROXY_URL` y `AGENT_MODEL` en `la-fabrique/.env`
  conservando comentarios y claves ajenas, y puede quitar `GEMINI_API_KEY` (por
  defecto lo hace: la instalación pasa a Nemotron). Prueba la clave contra
  `{base}/models` antes de guardarla; `run_fusion.py::_agent_model` devuelve
  `nvidia/nemotron-3-ultra-550b-a55b` cuando sólo hay `NEBIUS_API_KEY`.
  Después de guardar hay que reiniciar la fábrica: el proxy lee el `.env` al
  arrancar.
* **La puerta de NVIDIA es la de fábrica**: `DEFAULT_NEMOTRON_URL` es
  `https://integrate.api.nvidia.com/v1` y `DEFAULT_NEMOTRON_MODEL` es
  `nvidia/nemotron-3-ultra-550b-a55b` (el `llama-3.3-nemotron-super-49b-v1`
  anterior contestaba **410** en NVIDIA: retirado el 2026-08-26). Guardar escribe
  además la receta con la que el modelo está afinado —`temperature` 1, `top_p`
  0.95, `max_tokens` 16384 y `thinking`— sin pisar lo que el usuario ya haya
  puesto a mano en ⚙ PROVIDERS. `_body()` la manda, y el razonamiento va en
  `chat_template_kwargs.enable_thinking`, que es donde Nemotron lo lee (sólo se
  envía a NVIDIA/Nemotron: otro servidor rechazaría el campo). El
  `reasoning_content` del stream ya se acumulaba y **no se habla**: el motor lo
  separa del texto visible.
* `_FACTORY_KEYS` mapea cada host a sus nombres de variable, en orden: la puerta
  de NVIDIA acepta `NVIDIA_API_KEY` y, si no está, `NEBIUS_API_KEY` — el `.env`
  guarda una sola clave para Nemotron, y sin ese segundo nombre elegir NVIDIA
  dejaba la petición sin `Authorization` («authorization header missing»).
* **Un modelo retirado se reemplaza solo.** El proveedor contesta `410 Gone`
  y el id guardado no se puede quedar ahí: `OpenAICompatLLM._migrate()` consulta
  el catálogo **una vez**, prefiere el mismo fabricante y `DEFAULT_NEMOTRON_MODEL`,
  reintenta antes de la primera palabra (`chat()` no reintenta si ya habló) y
  `PipelineEngine._keep_migrated_model()` guarda el reemplazo en
  `providers.creds.openai_compat` **y** en el `AGENT_MODEL` del `.env` de la
  fábrica — si no, sus agentes siguen pidiendo el muerto. Fue el 410 de
  `llama-3.3-nemotron-super-49b-v1` el 2026-08-26: «AI online» y después nada.
  El 404 de un id que **sí** está en el catálogo no migra: ahí el problema es
  otro y cambiarlo lo escondería.
* **`faster-whisper` se instala sola, una vez.** El aviso decía «instalalo desde
  el panel de proveedores» y ese botón no existía: `WhisperSTT._install_once()`
  corre `sys.executable -m pip install faster-whisper` al arrancar el motor,
  informa en el registro y, si pip no puede (app empaquetada, sin red o sin
  permisos), imprime el comando exacto con el intérprete correcto. `_INSTALL_TRIED`
  es de clase: cambiar de motor no vuelve a lanzar pip.
* **Nemotron no tiene voz.** Es un modelo de texto, así que no puede sustituir
  a Gemini Live en el audio; lo que sí hace «Guardar» —con «Que el asistente
  piense con Nemotron» marcado— es cambiar el motor a `pipeline`: escribe
  `providers.creds.openai_compat` (base URL, modelo y la misma clave) y
  `providers.creds.whisper`, deja `mode = "pipeline"` y emite `applied`, que
  `ui.py::_open_models` conecta a `_on_providers_applied` para reconstruir la
  sesión sin cerrar la aplicación. El panel elige por defecto la primera voz
  instalada y que no cueste dinero, y avisa si la elegida no está instalada.
* **La voz puede venir de la misma cuenta** (`providers/tts_openai.py`,
  `openai_tts`): cualquier endpoint con `/v1/audio/speech` —Nebius, OpenAI, un
  servidor local— habla con la clave que ya paga el modelo. El panel no inventa
  nombres de modelo: al abrirse pregunta a `{base}/models` (en un hilo, sin
  bloquear) y sólo ofrece los que parecen voz, descartando `whisper`/`stt`; la
  opción se rotula con el modelo encontrado o con «sin voz publicada». Si al
  guardar no hay ninguno, cae a la voz anterior y lo dice en el mensaje, en vez
  de dejar al asistente mudo por un 404. Pide `pcm` (24 kHz mono s16le) y sólo
  baja a `mp3` si el servidor lo rechaza, que necesita PyAV.
* El panel Nemotron se cierra con la ✕ (30×30, con tooltip) o con **Escape**
  (`QShortcut`), ambos por `_close_panel()`.
* **El 401 tiene dos causas y el cuerpo del proveedor las distingue.**
  `Reason: token is not present` es que la petición salió sin `Authorization`:
  pasaba al elegir Nemotron en ⚙ con la clave sólo en el `.env` (el asistente lee
  `api_keys.json`), y `providers/llm_openai._factory_key()` ahora la toma de
  `NEBIUS_API_KEY` cuando el campo está vacío. `Reason: Unable authenticate` (o
  `403 Authorization failed` en NVIDIA) es que la clave salió y **fue
  rechazada** — y el mensaje lo dice así en vez de repetir el cuerpo.
* **El mismo modelo se sirve en tres puertas y cada clave vale en una sola**:
  Nebius Token Factory, Nebius AI Studio y NVIDIA NIM (`integrate.api.nvidia.com`,
  el mismo id `nvidia/…`). Las claves de las tres se parecen (`nvapi-…`), así que
  el prefijo no dice nada: `fabrica_env.probe_doors()` prueba la dirección escrita
  y después las otras dos, y **Probar clave** cambia la del panel a la que acepta.
  NVIDIA publica su catálogo sin clave, así que ahí la prueba es un
  `chat/completions` de un token con un modelo de chat del catálogo
  (`_nvidia_test_model` descarta embeddings, guardrails y parsers).
  `fabrica_env.clean_key()` quita comillas y `Bearer ` antes de escribir el
  `.env` y antes de mandar el encabezado.
* Un modelo retirado contesta **410 Gone** (NVIDIA lo dice con fecha); `_fail`
  lo explica en vez de dejarlo como «HTTP 410».
* **Ni Nebius ni NVIDIA sirven `/audio/transcriptions`** (404): la opción de
  escuchar por la API estaba puesta y dejaba al asistente sordo con un 404 en el
  registro. `fabrica_env.supports_transcription()` sondea la ruta (cuerpo basura:
  importa la ruta, no el resultado) y el panel **sólo añade esa opción al
  desplegable si la ruta existe**; si la config guardada la usaba y la ruta no
  está, `Guardar` deja el Whisper local y lo dice. `providers/stt_whisper` da un
  mensaje propio en el 404 en vez del `404 Not Found` pelado.
* `tests/test_modelos_panel.py` cubre el guardado de punta a punta (`.env`,
  `api_keys.json`, señal `applied`, interruptor apagado, clave ya guardada), la
  voz prestada por la API con y sin modelo publicado, el reintento en la otra
  puerta de Nebius y el cierre con la ✕ y con Escape.
  `tests/test_llm_key.py` cubre de dónde sale la clave (panel, `.env`, comillas)
  y qué dice cada 401. `tests/test_tts_api.py` cubre el filtro de modelos frente a
  los que transcriben, sin salir a la red.

Cómo comprobarlo sin pantalla:

    /tmp/venv-exe/bin/python tools/ui_check.py     # 98 checks + screenshots/v2
    /tmp/bevenv/bin/python -m pytest -q            # 48 + 16 tests

## Hackathon NVIDIA × Nebius (categoría: Coding & Agents Engineering)

* **Token Factory es la infraestructura por defecto.** `fabrica_env.DEFAULT_NEMOTRON_URL`
  es `https://api.tokenfactory.nebius.com/v1`; NVIDIA NIM sigue aceptándose como
  puerta alternativa (misma clave con prefijo `nvapi-`, el panel las prueba).
  `tests/test_fabrica_env.py::test_the_default_door_is_token_factory` lo fija.
* **Dos niveles, un proveedor.** El panel escribe `NEMOTRON_ROLES`,
  `NEMOTRON_MODEL`, `NEMOTRON_MODEL_STRATEGIC` y `NEMOTRON_MODEL_FAST` en
  `la-fabrique/.env`; `la-fabrique/backend/llm/model_factory.py` los aplica por
  rol. Los nombres de rol son `AgentRole.value` en minúsculas
  (`scrummaster`, `techwriter`, `engramprocessor`) — con guion bajo no coincide
  y el rol se queda en el mapa viejo **sin avisar**. Hay un test que lee el enum.
* **`tier_models(offered, default)`** reparte el catálogo en (razonamiento,
  rápido) y **sólo** escribe ids que el proveedor confirmó: un id inventado da
  400 en el primer turno de la fábrica.
* **`demo/coding_agent.py`** es la demostración funcional y el corazón del
  argumento de la categoría: el modelo propone archivos → se escriben en un
  directorio temporal (`_safe_path` rechaza rutas absolutas y `..`) → se ejecuta
  `unittest` → si falla, la salida real vuelve al modelo. `--offline` usa dos
  respuestas grabadas (una ronda que falla, otra que arregla) y es lo que corre
  en `tests/test_demo_agent.py` y en el verificador.
* **`tools/hackathon_check.py`** convierte los requisitos de la convocatoria en
  comprobaciones ejecutables (licencia, README, configuración, demo, claves no
  versionadas) y, con clave, la puerta que la acepta + catálogo Nemotron + un
  turno real. Con una clave que no es de Token Factory sale en amarillo, no en
  rojo: sirve para desarrollo, no para el envío.
* **Envío:** `SUBMISSION.md` (categoría, descripción, demo, guion del vídeo de
  3 min, feedback, qué existía antes). Antes de enviar hay que completar las
  URLs del repositorio y del vídeo.
* **Nombre y originalidad.** El asistente se llama **Asistente B1** (antes
  «Mark LVI») en código, config, spec, readme y docs. `profesor3/` **no es código
  propio**: es una obra derivada de *MARK 56 — JARVIS* de FatihMakes, CC BY-NC
  4.0 (`profesor3/LICENSE`). La atribución se conserva y no se puede relicenciar
  como Apache-2.0 ni presentar como autoría propia; lo original de este envío es
  la capa de fusión (~4.300 líneas: `/v1/voice/*`, `plugins/fabrica.py`,
  `core/fabrica_env.py`, proveedor Nemotron, demo, lanzador, verificador).
* **Guía de arranque, no noticias.** El briefing ya no pide titulares: muestra
  `plugins/fabrica.guide_text()` en el panel («FÁBRICA — QUÉ PODÉS PEDIR») y
  manda `guide_briefing()` al modelo (`main.py::_send_startup_briefing`). Un solo
  texto para pantalla y voz, para que la respuesta no invente capacidades. Los
  tests de la guía viven en `profesor3/tests/test_fabrica_plugin.py::GuideTest`.

