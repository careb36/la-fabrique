# Coding standards

> **Audience:** everyone writing code in this repository, whatever the role
> **Related:** [`CONTRIBUTING.md`](CONTRIBUTING.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), [`AGENTS.md`](AGENTS.md)
> **Last updated:** 2026-10-30

## 1. Purpose

One standard, written down, so reviews argue about the code and not about the
conventions. Every rule here is either enforced by a tool in CI or by a test in
the repository. A rule that nothing enforces is a preference, and the document
says which is which.

## 2. Principles

1. **Clarity before cleverness.** Write for the next maintainer.
2. **Consistency is a feature.** When in doubt, match the surrounding code.
3. **Failure is a feature.** A new path ships with its failure case tested, not
   only its happy path.
4. **Security by default.** Validate and log every external input.
5. **Observability for anything slow or asynchronous.** Structured events, not
   `print`.
6. **One canonical toolchain.** Do not introduce a second formatter, linter or
   package manager without an ADR.

## 3. Repository layout

Two independent Poetry projects (the backend and the LLM proxy) and an npm
project (the frontend). Each has its own lock file.

```
backend/app/          FastAPI: main.py wires routers, routers/ HTTP, services/ logic, models/ tables
backend/agents/       optional LangGraph producer
backend/llm/          role to model map (ModelFactory.ROLE_MODEL_MAP)
backend/memory/       pgvector RAG, Neo4j Engram nodes
backend/eval/         the verifier benchmark
backend/tests/        pytest, 57 modules
backend/janitor/      daily cleanup container
llm-proxy/            Flask gateway, its own Poetry project
frontend/src/         React 18 + Vite + TypeScript
frontend/electron/    desktop build
vscode-daemon/        host-side NATS consumer
scripts/e2e/          end-to-end run against real Postgres and NATS
db/init-db/           schema bootstrap for a fresh volume
deployment/k8s/       manifests
```

## 4. Python

**Version.** `^3.11` in `backend/pyproject.toml`. CI runs 3.12; the backend image
is `python:3.11-slim`. Do not use a feature that needs 3.12.

**Imports are top-level.** Tests run with `PYTHONPATH=.:app`, so modules import
`from config import settings` and `from models.sprint import BacklogItem`, not
`from app.config import ...`. Keep that style; a change to `app.`-prefixed
imports breaks every test.

**Types.** Annotate public functions. `mypy` runs in CI and is non-blocking
(`|| true`), so it will not fail your build, but a new error in a file you
touched is yours to fix.

**Sizes.** `scripts/check_file_sizes.py` is a CI gate with a ratchet: a file that
is already too long cannot grow. Split the module rather than raising the
threshold.

**Routers never touch the database.** They take `get_session` and
`auth_deps.get_current_user` injected and call `services/`. See
[`ARCHITECTURE.md`](ARCHITECTURE.md).

### Lint and format

There is no ruff configuration file, so ruff's defaults apply, and the default
rule set moves between releases. The version pinned in CI is the reference:

```bash
pip install "ruff==0.17.1"
cd backend && ruff check app tests && ruff format --check app tests
```

`black`, `isort` and `mypy` are Poetry dev dependencies; ruff is not, which is
why it is installed separately. Nothing enforces black or isort in CI — run
them if you like them, but ruff is what gates.

### Tests

```bash
cd backend && PYTHONPATH=.:app poetry run pytest tests -q
```

- Use the `sqlite_session` and `test_client` fixtures from
  `backend/tests/conftest.py`.
- **A new SQLModel table must be imported in that conftest**, or
  `SQLModel.metadata.create_all()` will not create it and the test will pass
  against nothing.
- The suite shares one in-memory database per run. Two tests that create a user
  with the same email make `select(...).one()` see two rows and fail, so make
  the email unique per test.
- No Postgres, NATS, Neo4j or model provider is needed. If a test needs one,
  it belongs in `scripts/e2e/`.

## 5. TypeScript and React

**Version.** Node 24 (`frontend/package.json` sets `engines.node >= 24.0.0`).

**State and data.** Zustand for client state, TanStack Query for anything that
calls the API. Do not add a second data-fetching library.

**The four gates**, in the order CI runs them:

```bash
cd frontend && npm ci && npx tsc --noEmit && npm run lint && npm run test:run && npm run build
```

Prettier is not a dependency: there is no TypeScript formatter in this
repository, and no workflow runs one.

### i18n is a build gate

Every user-facing string goes through `useTranslation` and lands in both
`frontend/src/i18n/en.json` and `es.json`.

- `npm run lint` runs `eslint-plugin-i18next`'s `no-literal-string` over JSX
  text and over the `title`, `alt`, `placeholder`, `aria-*` and `label`
  attributes. A hardcoded English literal fails the build.
- `src/i18n/coverage.test.ts` fails when a key passed to `t('…')` is missing
  from either locale.
- `src/i18n/locales.test.ts` requires `en.json` and `es.json` to have identical
  leaf key sets.

Use i18next `defaultValue` rather than `t(key) || fallback`: a missing key
returns the key, which is truthy, so the fallback never runs.

## 6. SQL and schema

No migration tool. `create_db_and_tables()` in `backend/app/database.py` runs
`SQLModel.metadata.create_all` and then `_ensure_runtime_schema()`, which applies
idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements.

To add a column to a released table, append the additive `ALTER TABLE` to
`_ensure_runtime_schema()`. Do not make a routine column addition depend on
resetting the volume.

Scope every company-owned row by `company_id`. Roles are Owner > Manager >
Viewer.

## 7. Security rules that bind code

- A provider API key is read only by `llm-proxy/`. A backend module that imports
  a provider SDK is a bug.
- A hash or signature is never taken from the party being recorded.
- A claim (what an agent says) and an observation (what the daemon reports) never
  share a field.
- Public routes are a short, deliberate list: `/health`, `/health/deep`,
  `/metrics`, `/openapi.json`, `/docs`, `/redoc`, register and login, the signed
  GitHub webhook, the public support form and chat, `/v1/models`,
  `/v1/capabilities`, and the ticketed Glassroom stream. Adding one is a security
  change, not a routing change.
- Never commit a key. CI does not scan for one (see [`SECURITY.md`](SECURITY.md)).

## 8. Dependencies

Add the dependency to the relevant `pyproject.toml` **and** commit the refreshed
`poetry.lock`. The frontend installs from `frontend/package-lock.json` with
`npm ci`, so that lock must be committed too.

## 9. Commits and reviews

Commit subjects are written in Spanish and usually carry a Conventional Commits
prefix (`fix:`, `feat:`, `docs:`, `ci:`, `test:`). Branch names are typed
(`fix/…`, `docs/…`, `ci/…`, `chore/…`), cut from `main`, one pull request each.
Fill in `.github/PULL_REQUEST_TEMPLATE.md` and reference an issue.

The template asks for observations, not claims: each command with its exit
status, or a link to the CI run. "Tests pass" without either does not count.
Leave out what you did not run rather than ticking it.
