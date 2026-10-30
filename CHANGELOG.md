# Changelog

All notable changes to the "La Fabrique" project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

* **Asistente B1, the coding-agent demo and the requirements checker, from the `fusion` branch.** `asistente-b1/` drives the factory by voice through `/v1/voice/*`; `demo/coding_agent.py` writes, runs and tests code until green (offline or on Nemotron); `tools/hackathon_check.py` checks the submission requirements. A new CI job runs their tests.
* **The factory by voice, from the `fusion` branch.** `/v1/voice/*` lets the desktop assistant check status, plan, create (paused), dispatch, pause, resume and decide through the same endpoints the web uses, behind a shared `VOICE_API_KEY`; `POST /v1/voice/build` writes a small project from one sentence into `FABRICA_BUILDS_DIR` and serves it sandboxed; `POST /v1/auth/desktop` opens the web UI signed in for the desktop operator; the backend serves the built UI same-origin. The proxy adds NVIDIA's own gateway (`NVIDIA_API_KEY`) for `nvidia/` ids, checks every id against the live catalogue, refuses `stream=true` with a 400 and trims CRLF from keys.
* **Nebius Token Factory as a first-class model provider.** The LLM proxy routes `nvidia/`, `meta-llama/`, `mistralai/`, `deepseek-ai/`, `qwen/` and `google/` model ids to Token Factory's OpenAI-compatible API, fetches the catalogue at startup and hourly, and lists what it found on `GET /v1/models`. `NEBIUS_API_KEY` enables it; `NEBIUS_PROXY_URL` retargets it at your own Serverless Endpoint. This is what serves the NVIDIA open models (Nemotron).
* **Per-role Nemotron opt-in.** `ModelFactory.model_for_role()` honours `NEMOTRON_ROLES` with `NEMOTRON_MODEL` / `_STRATEGIC` / `_FAST`, so agent roles can run on Nemotron. Unset, the Qwen/DeepSeek defaults are untouched.
* **Documentation overhaul.** README.md, README.es.md, CONTRIBUTING.md, and CLAUDE.md restructured following industry best practices. Added SECURITY.md, CODE_OF_CONDUCT.md, and GitHub issue/PR templates.
* **Architect consultation step.** Before a Developer starts a high-priority, design-sensitive, or QA-reworked task, the worker asks the company's Architect agent for a short technical brief, appends it to the card as an `ARCHITECT_CONSULTED:` comment (feeding the *Architect Consult Frequency* KPI), streams it to the Glassroom, and injects it into the Developer prompt. At most one consultation per implementation attempt. Disable with `ARCHITECT_CONSULT_ENABLED=false`.
* Backend tests for the KPI emitters and their contract with the analytics queries (`backend/tests/test_orchestration_metrics.py`).
* **Competition-ready documentation.** Repo description and topics, evidence-page screenshots, a `docs/README.md` index and a `docs/HACKATHON.md` entry page for the Nebius × NVIDIA Global AI Hackathon, plus a Roadmap and Responsible-use section in the README.

### Fixed

* **Orchestration health KPIs were structurally zero.** `GET /v1/analytics/orchestration_health` filtered `audit_log` on `details.role` / `details.company_id` and counted `ARCHITECT_CONSULTED:` comments, but the task pipeline never wrote either. The worker now records every Developer execution and QA review to `audit_log` (canonical role, company scope, `result_type`, proxy-reported token cost) via the new `services/orchestration_metrics.py` module, so *Avg Developer Tokens* and the QA *NEEDS WORK* rate read real data.

---

## Versioning

There is no tagged release yet: the project has not been versioned since the
original scaffold, and `main` is the web product. The changes above are the
accumulated work between the initial scaffold and the current head.

[unreleased]: https://github.com/careb36/la-fabrique/commits/main
