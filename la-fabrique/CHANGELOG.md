# Changelog

All notable changes to the "La Fabrique" project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

* **Asistente B1, the coding-agent demo and the requirements checker, from the `fusion` branch, after a security review.** `asistente-b1/` drives the factory by voice through `/v1/voice/*`; `demo/coding_agent.py` writes, runs and tests code until green (offline or on Nemotron); `tools/hackathon_check.py` checks the submission requirements. A new CI job runs their tests. The review's fixes: decisive factory actions run only after the person says "sí, confirmo" (checked in code, not in the prompt); only the factory's previews are opened; keys do not follow cross-origin redirects; Windows speech passes text as data, never as PowerShell source; a leading dash is not read as an option; `config.json` is created 0600; the demo runs model-written tests without the parent's environment.
* **The factory by voice, from the `fusion` branch.** `/v1/voice/*` lets the desktop assistant check status, plan, create (paused), dispatch, pause, resume and decide through the same endpoints the web uses, behind a shared `VOICE_API_KEY`; `POST /v1/voice/build` writes a small project from one sentence into `FABRICA_BUILDS_DIR` and serves it sandboxed; `POST /v1/auth/desktop` opens the web UI signed in for the desktop operator; the backend serves the built UI same-origin. The proxy adds NVIDIA's own gateway (`NVIDIA_API_KEY`) for `nvidia/` ids, checks every id against the live catalogue, refuses `stream=true` with a 400 and trims CRLF from keys.
* **Nebius Token Factory as a first-class model provider.** The LLM proxy routes `nvidia/`, `meta-llama/`, `mistralai/`, `deepseek-ai/`, `qwen/` and `google/` model ids to Token Factory's OpenAI-compatible API, fetches the catalogue at startup and hourly, and lists what it found on `GET /v1/models`. `NEBIUS_API_KEY` enables it; `NEBIUS_PROXY_URL` retargets it at your own Serverless Endpoint. This is what serves the NVIDIA open models (Nemotron).
* **Per-role Nemotron opt-in.** `ModelFactory.model_for_role()` honours `NEMOTRON_ROLES` with `NEMOTRON_MODEL` / `_STRATEGIC` / `_FAST`, so agent roles can run on Nemotron. Unset, the Qwen/DeepSeek defaults are untouched.
* **Documentation overhaul.** README.md, README.es.md, CONTRIBUTING.md, and CLAUDE.md restructured following industry best practices. Added SECURITY.md, CODE_OF_CONDUCT.md, and GitHub issue/PR templates.
* **Architect consultation step.** Before a Developer starts a high-priority, design-sensitive, or QA-reworked task, the worker asks the company's Architect agent for a short technical brief, appends it to the card as an `ARCHITECT_CONSULTED:` comment (feeding the *Architect Consult Frequency* KPI), streams it to the Glassroom, and injects it into the Developer prompt. At most one consultation per implementation attempt. Disable with `ARCHITECT_CONSULT_ENABLED=false`.
* Backend tests for the KPI emitters and their contract with the analytics queries (`backend/tests/test_orchestration_metrics.py`).
* **Competition-ready documentation.** Repo description and topics, evidence-page screenshots, a `docs/README.md` index and a `docs/HACKATHON.md` entry page for the Nebius × NVIDIA Global AI Hackathon, plus a Roadmap and Responsible-use section in the README.

### Fixed

* **Security pass over the whole repository.** Frontend dependencies moved past every known advisory (`npm audit`: 0, from 2 critical and 3 high): React Router 7, Vite 8, Vitest 5, Electron 45. Login, registration and the desktop key exchange are rate-limited (`AUTH_RATE_LIMIT`); a 500 now carries the security headers; every container runs as a non-root user (the compose daemon as `DAEMON_UID`, and it now mounts the modules `daemon.py` imports); every GitHub Action is pinned to a commit SHA; the release workflow no longer pastes the tag name into shell scripts; the desktop assistant refuses to send a key over plain http to another machine. pip-audit on the backend and proxy locks, Bandit, Semgrep and gitleaks over the history found nothing else.

* **Voice routes: tenant isolation and the desktop account (security review of the `fusion` port).** A signed-in user could read and change any company through `/v1/voice/*` (no membership check), the voice key reached every company, the desktop Owner account could be claimed by registering its email first, approvals by key were recorded under a name the assistant chose, a non-ASCII key header gave a 500, `extra_body.stream` slipped past the proxy's stream refusal, and the URL session handoff replaced an open session. Each is fixed and covered by `test_voice_access.py` or the proxy tests; build previews also get a random folder name, a 4,000-character request cap and no `allow-forms`.

* **Orchestration health KPIs were structurally zero.** `GET /v1/analytics/orchestration_health` filtered `audit_log` on `details.role` / `details.company_id` and counted `ARCHITECT_CONSULTED:` comments, but the task pipeline never wrote either. The worker now records every Developer execution and QA review to `audit_log` (canonical role, company scope, `result_type`, proxy-reported token cost) via the new `services/orchestration_metrics.py` module, so *Avg Developer Tokens* and the QA *NEEDS WORK* rate read real data.

---

## Versioning

There is no tagged release yet: the project has not been versioned since the
original scaffold, and `main` is the web product. The changes above are the
accumulated work between the initial scaffold and the current head.

[unreleased]: https://github.com/careb36/la-fabrique/commits/main
