# Copilot Instructions

La Fabrique orchestrates AI agents (PO, Architect, Developer, QA, …) over a user's VS Code workspace. **Direction (see `docs/POSITIONING.md`, issue #38):** agents are interchangeable producers; the product is the layer that verifies their work and records evidence. Read that document before planning new work. `CLAUDE.md` has further detail.

## Build, test, lint

```bash
# Backend tests (no Postgres/NATS/Neo4j/LLM needed; in-memory SQLite + mocks)
cd backend && PYTHONPATH=.:app python3 -m pytest tests -q
# Single file / single test
cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_verification.py -q
cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_verification.py::test_name -q

# Frontend (from frontend/) — CI runs these four in order
npm ci && npx tsc --noEmit && npm run test:run && npm run build
npx vitest run src/components/AnalyticsDashboard.test.tsx   # single file

# Run services
docker compose up -d                 # full stack
make dev-backend | dev-llm-proxy | dev-frontend   # local (Poetry / Vite)
python vscode-daemon/daemon.py       # must run on the host, not in Docker
```

- No Python linter is configured. Backend CI uses Poetry (Python 3.12) and runs `poetry check --lock`: when adding a backend dependency, update `backend/pyproject.toml` **and** commit the refreshed `poetry.lock`.
- Backend modules are imported as top-level (`from config import settings`, `from models.company import ...`) because tests set `PYTHONPATH=.:app`. Keep that import style.

## Architecture

- **Backend** (`backend/app/`, FastAPI + SQLModel): `main.py` wires app startup and `include_router` for `routers/` (auth, enterprise, sprint, agents, agent_runs, support, github). Business logic lives in `services/`, tables in `models/`. Keep DB logic out of controllers and inject dependencies (`get_session`, `auth_deps.get_current_user`).
- **Evidence layer:** external agent runs are ingested as `AgentRun` (+ `AgentRunApproval`, `Verification`) via `routers/agent_runs.py`, `services/agent_run_service.py`, and `services/verification.py`. The optional LangGraph producer (`backend/agents/graph.py`, only when `AGENT_GRAPH_ENABLED=true`) is just one producer (`producer: "le-fabrique-graph"`).
- **Messaging:** sprints/events go through a transactional outbox (`OutboxEvent`, `services/outbox_service.py`) to NATS JetStream; `vscode-daemon/daemon.py` consumes `workspace.generate` / `workspace.execute` to write files and run shell commands locally. `backend/janitor/` does daily cleanup/reindexing.
- **LLM access:** the backend never calls Gemini/DeepSeek directly; it goes through `llm_proxy_client.py` → `llm-proxy/app.py` (Flask, per-company token budgets). Pass `model_preference="fast"` (default) or `"powerful"` (Architect/high-stakes only). Role→model mapping is in `backend/llm/model_factory.py`.
- **Memory:** pgvector for RAG (`/v1/memory/*`), Neo4j "Engram" nodes for immutable decision lineage (`backend/memory/engram_processor.py`).
- **Frontend** (`frontend/src/`, React 18 + Vite + TS + Tailwind): Zustand for state, TanStack Query for API calls; Glassroom uses SSE.

## Conventions

- **Verification design rules (don't violate):** a claim and an observation never share a field; an agent's report of its own test run is a claim, not an observation; `unverifiable` is a distinct verdict from `verified`/`refuted`; never use an LLM to decide whether a claim holds; hashes/signatures are never accepted from the party being recorded.
- **Multi-tenancy/auth:** all data is scoped by `company_id`. Roles: Owner > Manager > Viewer. Audit writes and memory stores derive company ownership from authenticated membership, never from payload metadata. Auth is enforced by default (`AUTH_REQUIRED`); public routes are limited (`/health`, register/login, signed GitHub webhook, support bug/chat, `/v1/models`, Glassroom SSE, `/v1/approve_task` → 410).
- **i18n:** every user-facing string goes in both `frontend/src/i18n/en.json` and `es.json` (CONTRIBUTING.md mentions `locales/`, but the real path is `i18n/`), via `useTranslation`. Use i18next `defaultValue`, not `t(key) || fallback` (a missing key returns the key, which is truthy).
- **Tests:** new backend tests use fixtures from `backend/tests/conftest.py` (`sqlite_session`, `test_client`); register any new SQLModel table imports there so `create_all` sees them.
- **Git:** trunk-based — branch `feature/*` / `bugfix/*` / `docs/*` / `fix/*` from `main`, PRs target `main`, merge commit (not a squash). Conventional Commits `type(scope): description`. Fill in `.github/PULL_REQUEST_TEMPLATE.md`, and only claim a green build/tests you actually ran.
- Secrets (`FERNET_SECRET_KEY`, `JWT_SECRET_KEY`, `AUDIT_SIGNING_KEY`, API keys) come from `.env` (see `.env.example`); never commit them.
