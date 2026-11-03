# Changelog

All notable changes to the "La Fabrique" project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

* **Asistente B1, the coding-agent demo and the requirements checker left `main`.** `main` is the web product; the voice assistant lives on the `fusion` and `meta-vr` branches. `asistente-b1/`, `demo/`, `tests/` (the demo's), `tools/hackathon_check.py` and the `assistant-tests` workflow are gone from here, and so are the backend's `/v1/voice/*` and `/v1/voice/build` routes, the `/v1/auth/desktop` key exchange and handoff (with the web UI's `#codigo=` redeem), `VOICE_API_KEY`, `VOICE_COMPANY_ID`, `FABRICA_BUILDS_DIR` and `FRAME_ANCESTORS`. The voice assistant and the factory-by-voice routes had been ported here from `fusion` earlier in this cycle and were never released from `main`.
* **No model provider is the default.** `NEMOTRON_ROLES`, `NEMOTRON_MODEL`, `NEMOTRON_MODEL_STRATEGIC` and `NEMOTRON_MODEL_FAST` are gone, with the `.env.example` that opted every role into one vendor; `docs/HACKATHON.md` (the competition entry page) left `main` for the `fusion` branch. The README's provider section lists every provider alike.

### Added

* **Two more model providers, routed like the others.** The LLM proxy reaches Nebius Token Factory (`NEBIUS_API_KEY`, `nvidia/`, `meta-llama/`, `mistralai/`, `deepseek-ai/`, `qwen/` and `google/` ids; `NEBIUS_PROXY_URL` retargets it at a Serverless Endpoint) and NVIDIA's own gateway (`NVIDIA_API_KEY`, `nvidia/` ids). Every provider's catalogue is fetched at startup and hourly and listed on `GET /v1/models`; an id in no catalogue is refused at the door; `stream=true` gets a 400; CRLF is trimmed from keys.
* **A model per role, from any provider.** `AGENT_MODEL` points every role at one model id; `AGENT_MODEL_<ROLE>` (`AGENT_MODEL_PO`, `AGENT_MODEL_DEVELOPER`, …) gives one role its own and wins over it. Unset, the role keeps the built-in map in `backend/llm/model_factory.py`, a default any deployment overrides.
* **Documentation overhaul.** README.md, README.es.md and CONTRIBUTING.md restructured following industry best practices. Added SECURITY.md, CODE_OF_CONDUCT.md, and GitHub issue/PR templates.
* **Architect consultation step.** Before a Developer starts a high-priority, design-sensitive, or QA-reworked task, the worker asks the company's Architect agent for a short technical brief, appends it to the card as an `ARCHITECT_CONSULTED:` comment (feeding the *Architect Consult Frequency* KPI), streams it to the Glassroom, and injects it into the Developer prompt. At most one consultation per implementation attempt. Disable with `ARCHITECT_CONSULT_ENABLED=false`.
* Backend tests for the KPI emitters and their contract with the analytics queries (`backend/tests/test_orchestration_metrics.py`).
* **Documentation index and responsible use.** Evidence-page screenshots, a `docs/README.md` index, and a Responsible-use section in the README.

### Changed

* **Fewer tokens per task, with the evidence design unchanged.** A send-back by the Quality gate or the Verifier no longer earns a second Architect brief (it asked for the same deliverable); a rework quotes the console assistants' first advice instead of running the CLIs again; a review answer without `APPROVED:`/`NEEDS WORK:` is asked again with the format named; a Developer answer the model cut at its length limit is sent back as such (`finish_reason: length`, which the proxy now reports for Gemini too) rather than as "deliver the complete result again". The proxy client retries only a request that never reached the proxy (an error the proxy answered already cost its upstream call and fallbacks), waits as long as the proxy's own budget (`LLM_UPSTREAM_TIMEOUT_SECONDS` + 10 s; the planner's 12 s and the triage's 45 s discarded answers already billed), and caps the fixed-form answers (`max_tokens`: QA review, Architect brief, ScrumMaster, planner, Support and Reviewer agents). The Developer's deliverable keeps no cap, since every file goes in full.

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
