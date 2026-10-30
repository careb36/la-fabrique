# La Fabrique — CODING_STANDARDS.md

> **Status:** Canonical style guide for all La Fabrique engineering roles
> **Audience:** Backend/AI orchestration, Frontend, Security, DevOps, QA, Architect
> **Related documents:** `docs/architecture.md`, `docs/adr/`, `README.md`
> **Version:** Sprint 0 — Foundations
> **Last updated:** 2025-04-03

---

## 1. Purpose

This document defines the canonical coding standards, conventions, and tooling for the La Fabrique platform. It exists so that:

- Reviewers can enforce a single, consistent standard across Python, TypeScript, SQLAlchemy, LangGraph, FastAPI, React, and Vite.
- Every engineer—regardless of role—has a clear, role-specific quickstart and the exact lint/test commands they need.
- The codebase remains readable, testable, observable, secure, and maintainable as the system evolves.

This document is **the** canonical style guide. If a rule is missing, open an ADR or bring it to the Architect before inventing a local convention.

---

## 2. General Principles

1. **Clarity before cleverness.** Write code for the next maintainer, not for the compiler.
2. **Consistency is a feature.** When in doubt, match existing patterns.
3. **Test-driven, failure-aware.** Every new feature includes tests for the happy path and the failure modes.
4. **Security by default.** Tool calls, user inputs, and external data must be validated, escaped, and logged carefully.
5. **Observability first.** All long-running or async work must emit structured events for GlassRoom SSE consumers.
6. **Idempotent APIs.** Mutating endpoints must support `Idempotency-Key` where required.
7. **One canonical toolchain.** Use the commands and tools pinned in this document; do not introduce alternative formatters, linters, or package managers without an ADR.

---

## 3. Repository Toolchain

### 3.1 Monorepo layout
