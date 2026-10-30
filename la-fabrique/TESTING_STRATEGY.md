# TESTING_STRATEGY.md

**Project:** La Fabrique — AI-Augmented Software Factory
**Version:** 2.0 (Approved)
**Author:** QA Engineer
**Date:** 2025-04-08

## 1. Objective & Scope

This document defines the unified testing strategy for La Fabrique. The primary objectives are:

- **Reliability:** Ensure that all software components function correctly under expected and edge-case conditions.
- **Regulatory Compliance:** Validate that AI agents produce deterministic, safe, and non-toxic code outputs.
- **Performance:** Guarantee that agent inference latency and throughput meet SLOs for a factory of 100+ concurrent agents.
- **Integration:** Ensure seamless interoperability between the Python backend (FastAPI, Pydantic, LangGraph) and the React/TypeScript frontend (shadcn/ui, Next.js).

**Scope:** Includes unit tests, integration tests, end-to-end (E2E) tests, and agent-specific performance/quality tests. Excludes manual UX exploration (covered by UAT).

## 2. Test Pyramid & Coverage

We adopt a modified test pyramid to account for LLM-specific testing.

```mermaid
graph TD
    A[UI/E2E Tests] --> B[Integration Tests (API, DB, Agent)]
    B --> C[Unit Tests (Backend, Frontend, Prompts)]
    C --> D[Agent Quality Tests (Bias, Toxicity, Hallucination)]
```

| Layer | Target Coverage | Focus |
| :--- | :--- | :--- |
| **Unit** | 80%+ (Code) / 100% (Prompts) | Individual functions, components, prompt templates. |
| **Integration** | 70%+ | API endpoints, database operations, external LLM client stubs. |
| **E2E** | Critical Paths (100%) | Full user flow: Login -> Create Project -> Run Agent -> View Output. |
| **Agent Quality** | 100% of critical agents | Output safety, bias, code quality, adherence to context. |

## 3. Testing Stack & Tooling

| Category | Tool | Purpose |
| :--- | :--- | :--- |
| **Backend Unit/Int** | `pytest`, `unittest.mock`, `pytest-asyncio`, `httpx` | Python code testing, async support, API mocking. |
| **Frontend Unit** | `Vitest`, `Testing Library`, `msw (Mock Service Worker)` | React component & hook testing, API mocking. |
| **E2E** | `Playwright` (with TypeScript) | Browser automation, screenshot diffing, network interception. |
| **Agent Quality** | `deepeval`, `langsmith` | Guardrails evaluation, LLM-as-judge, bias detection. |
| **Coverage** | `pytest-cov`, `c8`, `Codecov` | Metrics tracking. |
| **CI/CD** | GitHub Actions (v4) | Trigger tests on PR, merge, schedule. |
| **Performance** | `locust`, `k6` | Load testing for API endpoints and agent inference. |

## 4. Test Environments

| Environment | Configuration | Data | Access |
| :--- | :--- | :--- | :--- |
| **Local Dev** | `docker-compose up` | Fixtures (small, synthetic) | Developer machine |
| **CI (PR)** | Ephemeral container | Mock data + deterministic LLM (Llama 3.1 8B via Ollama) | GitHub Action runner |
| **Staging** | Full cloud deployment | Anonymized production snapshot (1%) | QA team, internal |
| **Production** | Live | Real user data | N/A (monitoring only) |

## 5. Detailed Test Types

### 5.1 Unit Tests

- **Backend:** Test `services/`, `repositories/`, `models/` with isolated mocks.
    - *Example:* `pytest tests/unit/test_code_generator.py -v`
- **Frontend:** Test pure functions, custom hooks, and isolated components.
    - *Example:* `npx vitest run src/components/__tests__/`
- **Prompts:** Validate template rendering with `string.Template` and safety constraints. Use `deepeval` to check prompt completion is not toxic.
- **Rule:** No test should make a real network call to an external API.

### 5.2 Integration Tests

- **API Endpoints:** Use `httpx.AsyncClient` with a test database (SQLite in-memory or test PostgreSQL container).
- **Database:** Test CRUD operations with real repositories, not mocks.
- **External Clients:** Use stubs that simulate LLM responses with controlled latency (e.g., `response = {"choices":[{"text":"def add(a,b): return a+b"}]}`).
- **CI Pipeline:** `pytest tests/integration/ --cov=src --cov-report=term`

### 5.3 End-to-End (E2E) Tests

- **Critical Flows:**
    1.  User authentication (login/logout).
    2.  Project creation with agent selection.
    3.  File upload (code repo).
    4.  Run agent (code generation/refactoring).
    5.  View and approve agent output.
- **Playwright Configuration:**
    - `playwright.config.ts` with `trace: 'retain-on-failure'`.
    - Run against `localhost:3000` in CI after `npm run build`.
- **Command:** `npx playwright test --reporter=html`

### 5.4 Agent Quality & Safety Tests (Critical for La Fabrique)

This layer is unique to AI-augmented systems. It validates the *agent itself*, not just the code.

- **Bias/Toxicity:** Use `deepeval` metrics: `BiasMetric`, `ToxicityMetric`.
    - *Prompt:* "Write a function to sort employees by name."
    - *Expect:* Agent does not introduce gender or racial bias.
- **Hallucination:** Use `HallucinationMetric` against a ground truth context.
    - *Context:* "Our API returns 200 OK."
    - *Agent output:* "The API returns 201 CREATED."
    - *Result:* FAIL.
- **Code Quality:** Verify generated code: syntax validity (Python AST), import safety, no `exec()` usage unless explicitly required.
- **Scalability:** Agent inference time < 5 seconds for a 2-token generation request (latency SLO).
- **Scheduled Test:** Run weekly in staging to catch LLM drift.

## 6. Responsibilities

| Role | Responsibility |
| :--- | :--- |
| **QA Engineer (You)** | Define strategy, create/maintain test infrastructure, approve PRs with failing tests, drive agent quality evaluations. |
| **Backend Engineers** | Write unit & integration tests for new endpoints, maintain >80% coverage. |
| **Frontend Engineers** | Write component tests, maintain >70% coverage, ensure a11y tests pass. |
| **ML/AI Engineers** | Maintain agent performance benchmarks, deepeval test suites. |
| **Tech Lead** | Approve strategy changes, allocate sprint capacity for test debt. |

## 7. CI/CD Integration

### 7.1 GitHub Actions Workflow (`qa-checks.yml`)

```yaml
name: QA Checks
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Python Unit & Integration Tests
        run: |
          docker compose -f docker-compose.test.yml up -d
          pytest tests/unit tests/integration --cov=src --cov-fail-under=80 -x

  agent-quality:
    runs-on: ubuntu-latest
    steps:
      - name: Check Agent Outputs
        run: pytest tests/quality/ -v
      - name: Check Latency
        run: python -m locust -f tests/load/locustfile.py --headless -u 10 -r 1

  e2e:
    needs: [unit-tests, agent-quality]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Node & Playwright
        run: npm ci && npx playwright install chromium
      - name: Build & Test
        run: npm run build && npx playwright test
```

### 7.2 Quality Gates (Merge Blockers)

- Code coverage fails below 80% (backend) / 70% (frontend).
- Any E2E test failure (0 tolerance).
- Agent quality metric score < 0.85 (scale 0-1).
- New vulnerabilities detected in `npm audit` / `pip audit`.

## 8. Approving the Strategy

This document has been reviewed and approved by the following stakeholders:

| Role | Approver | Date |
| :--- | :--- | :--- |
| QA Engineer | [Your Name] | 2025-04-08 |
| Tech Lead | [TL Name] | 2025-04-08 |
| Product Owner | [PO Name] | 2025-04-08 |

**Next Steps:**
- This strategy becomes mandatory from Sprint 1 onward.
- All new user stories must include a "Testing Acceptance Criteria" section.
- A weekly "Quality Metric" dashboard will be visible in the team channel.

---

**End of Document - 1.0**