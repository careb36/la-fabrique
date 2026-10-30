# Changelog

All notable changes to the "La Fabrique" project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

* **Nebius Token Factory as a first-class model provider.** The LLM proxy routes `nvidia/`, `meta-llama/`, `mistralai/`, `deepseek-ai/`, `qwen/` and `google/` model ids to Token Factory's OpenAI-compatible API, fetches the catalogue at startup and hourly, and lists what it found on `GET /v1/models`. `NEBIUS_API_KEY` enables it; `NEBIUS_PROXY_URL` retargets it at your own Serverless Endpoint. This is what serves the NVIDIA open models (Nemotron).
* **Per-role Nemotron opt-in.** `ModelFactory.model_for_role()` honours `NEMOTRON_ROLES` with `NEMOTRON_MODEL` / `_STRATEGIC` / `_FAST`, so agent roles can run on Nemotron. Unset, the Qwen/DeepSeek defaults are untouched.
* **Documentation overhaul.** README.md, README.es.md, CONTRIBUTING.md, and CLAUDE.md restructured following industry best practices. Added SECURITY.md, CODE_OF_CONDUCT.md, and GitHub issue/PR templates.
* **Architect consultation step.** Before a Developer starts a high-priority, design-sensitive, or QA-reworked task, the worker asks the company's Architect agent for a short technical brief, appends it to the card as an `ARCHITECT_CONSULTED:` comment (feeding the *Architect Consult Frequency* KPI), streams it to the Glassroom, and injects it into the Developer prompt. At most one consultation per implementation attempt. Disable with `ARCHITECT_CONSULT_ENABLED=false`.
* Backend tests for the KPI emitters and their contract with the analytics queries (`backend/tests/test_orchestration_metrics.py`).

### Fixed

* **Orchestration health KPIs were structurally zero.** `GET /v1/analytics/orchestration_health` filtered `audit_log` on `details.role` / `details.company_id` and counted `ARCHITECT_CONSULTED:` comments, but the task pipeline never wrote either. The worker now records every Developer execution and QA review to `audit_log` (canonical role, company scope, `result_type`, proxy-reported token cost) via the new `services/orchestration_metrics.py` module, so *Avg Developer Tokens* and the QA *NEEDS WORK* rate read real data.

---

## [0.1.0] - 2023-10-27

### Added

* **Project Initialization:** Established the initial project structure, including the core application scaffolding, configuration files, and directory layout for the La Fabrique platform.
* **Core Agent Service:** Implemented the foundational agent orchestration service. This service is responsible for receiving high-level development tasks, decomposing them into sub-tasks, and managing the execution lifecycle.
* **Tooling Integration Framework (Alpha):** Created the basic infrastructure for integrating external developer tools. This initial version includes placeholder interfaces for linters, compilers, and version control systems.
* **Prompt Engineering Library:** Seeded the initial library of system prompts and templates for core tasks like code generation, debugging, and test creation. This provides a baseline for the AI's operational capabilities.
* **CI/CD Pipeline Foundation:** Set up the initial continuous integration and deployment pipeline using GitHub Actions. The pipeline currently handles automated builds and runs placeholder unit tests on every commit to the `main` branch.
* **Core Documentation:** Created essential project documentation including `README.md`, `CONTRIBUTING.md`, and this `CHANGELOG.md` to establish development standards and provide a baseline for future contributors.

[unreleased]: https://github.com/careb36/la-fabrique/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/careb36/la-fabrique/releases/tag/v0.1.0
