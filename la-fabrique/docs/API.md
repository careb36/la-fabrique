# API reference

The FastAPI control plane on port 8000. This page is the map and the walkthrough
of one sprint; the exhaustive list, with request and response schemas, is
generated from the code:

- `GET /openapi.json` — the specification
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

Start the backend to read them:

```bash
cd backend && PYTHONPATH=.:app poetry run uvicorn app.main:app --reload --port 8000
```

`make dev-backend` runs the same command with the same `PYTHONPATH`. It fails
with `Address already in use` while the compose stack holds port 8000, so stop
`docker compose` (or the `backend` service) first.

## Base URL and authentication

```
http://localhost:8000
```

Most endpoints require a bearer token:

```
Authorization: Bearer <access_token>
```

Auth is enforced by default (`AUTH_REQUIRED=true`). Login answers 503 until
`JWT_SECRET_KEY` is set.

### Getting a token

```bash
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass123", "full_name": "John Doe"}'

curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass123"}'
```

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

Passwords are hashed with bcrypt directly, capped at 72 bytes, because bcrypt
silently ignores anything past that length. A longer password is rejected at
registration with 422 rather than accepted and truncated.

The three authentication endpoints:

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/auth/register` | Create the user and its first company membership |
| `POST` | `/v1/auth/login` | Issue the JWT |
| `GET` | `/v1/auth/me` | The caller's identity and memberships |

### Roles and scope

Roles are Owner > Manager > Viewer, per company. Every company-owned row is
scoped by `company_id`; a token that is not a member of the company gets 403,
and a row that does not exist gets 404. A caller with several memberships should
pass the `company_id` query parameter where the endpoint accepts one.

### Public routes

A short, deliberate list: `/health`, `/health/deep`, `/metrics`,
`/openapi.json`, `/docs`, `/redoc`, register and login, the HMAC-signed GitHub
webhook, the support bug form and chat, `/v1/models`, `/v1/capabilities`, and
the retired `/v1/approve_task` (410).

Glassroom SSE cannot carry an `Authorization` header, because `EventSource`
sends none. With `AUTH_REQUIRED` it takes a short-lived `ticket` for one sprint
from `POST /v1/sprints/{sprint_id}/stream_ticket`, and rechecks the holder's
membership when the ticket is used.

## Route index

72 route entries across 11 routers, which is 68 operations in the OpenAPI
schema (`/health` answers `HEAD` as well, and `HEAD` is not an operation).
Grouped here by the module that owns them, which is how the code is organised;
the OpenAPI tags do not follow the module boundaries.

### Core — `routers/sprint.py`, `routers/enterprise.py`

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/init_company` | Bootstrap a tenant and its agents |
| `POST` | `/v1/plan_sprint` | Plan without starting |
| `POST` | `/v1/plan_self_improvement_sprint` | Plan from the factory's own findings |
| `POST` | `/v1/start_sprint` | Create a sprint with its backlog |
| `GET` | `/v1/sprints` | List |
| `GET` | `/v1/sprints/{sprint_id}/board` | Board state |
| `POST` | `/v1/sprints/{sprint_id}/dispatch` | Send the sprint through the outbox |
| `POST` | `/v1/sprints/{sprint_id}/pause` | |
| `POST` | `/v1/sprints/{sprint_id}/resume` | |
| `POST` | `/v1/sprints/{sprint_id}/stream_ticket` | Ticket for the SSE stream |
| `PATCH` | `/v1/backlog/{item_id}` | Move or edit a backlog item |
| `POST` | `/v1/discover_team` | Propose a team for a project |
| `POST` | `/v1/generate` | Free-form generation through the proxy |

### Agent runs and verification — `routers/agent_runs.py`

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/agent_runs` | Ingest what an agent says it did |
| `GET` | `/v1/agent_runs` | List |
| `GET` | `/v1/agent_runs/{run_id}` | One run |
| `POST` | `/v1/agent_runs/{run_id}/verify` | **Verify against evidence** (Manager) |
| `GET` | `/v1/agent_runs/{run_id}/verifications` | Every verdict for the run |
| `POST` | `/v1/agent_runs/{run_id}/approve` | A person decides (Manager) |
| `GET` | `/v1/agent_runs/{run_id}/approvals` | The decisions |
| `GET` | `/v1/agent_runs/reviewer_record` | What the reviewer has ruled |

### Agents — `routers/agents.py`

| Method | Path | Notes |
|---|---|---|
| `GET` `POST` | `/v1/agents` | List, create |
| `PATCH` `DELETE` | `/v1/agents/{agent_id}` | Update, remove |
| `POST` | `/v1/agents/generate_prompt` | Draft a role prompt |
| `GET` | `/v1/glassroom/stream` | SSE of agent events for a sprint |
| `GET` | `/v1/memory/search` | pgvector plus Neo4j |
| `POST` | `/v1/memory/store` | Persist content and embedding |
| `POST` | `/v1/audit` | Append a signed audit entry |
| `GET` | `/v1/audit/chain` | The hash chain |
| `GET` | `/v1/audit/verify` | Recheck the chain |
| `GET` `POST` | `/v1/procedures` | Learnt procedures |
| `POST` | `/v1/procedures/{procedure_id}/adopt` | |
| `POST` | `/v1/procedures/{procedure_id}/reject` | |
| `POST` | `/v1/procedures/{procedure_id}/retire` | |
| `GET` | `/v1/messages` | Message log |

### Enterprise — `routers/enterprise.py`

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/enterprise/quotas` | Token budget per business unit |
| `POST` | `/v1/enterprise/quotas/{bu_id}/reset` | |
| `GET` | `/v1/enterprise/quota_usage_history` | |
| `GET` | `/v1/enterprise/lineage` | Decision lineage |
| `GET` | `/v1/analytics/summary` | |
| `GET` | `/v1/analytics/orchestration_health` | |
| `GET` | `/v1/capabilities` | Which features are configured, no company data |
| `GET` | `/v1/models` | Models the proxy exposes, by tier |
| `POST` | `/v1/company/invite` | |

### GitHub — `routers/github.py`

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/integrations/github/webhook` | HMAC-signed; public |
| `POST` | `/v1/integrations/github/bindings` | Link a repo to a company |
| `POST` | `/v1/integrations/github/backfill` | Pull historical runs |

### Support — `routers/support.py`

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/support/report_bug` | Public form |
| `POST` | `/v1/support/chat` | Public chat |
| `GET` | `/v1/support/tickets` | Admins see all; others see their own |
| `GET` `PATCH` | `/v1/support/tickets/{ticket_num}` | |
| `GET` | `/v1/support/logs` | Admin only |
| `GET` | `/v1/support/agent_record` | What the support agent did |

### Workspace — `routers/workspace.py`

What the daemon reports about the folder the person opened. These are
observations, never agent claims.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/workspace/status` | Is a daemon reachable |
| `GET` | `/v1/workspace/inspect` | Trees, files |
| `GET` | `/v1/workspace/browse` | Browse a path |

### Inbox and messages — `routers/inbox.py`, `routers/messages.py`

| Method | Path |
|---|---|
| `GET` | `/v1/inbox` |
| `GET` | `/v1/messages` |

### Operational — `main.py`

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness, no auth |
| `GET` | `/health/deep` | Dependency checks |
| `GET` | `/metrics` | Prometheus |

## Walking one sprint

### 1. Create the company

```bash
curl -X POST http://localhost:8000/v1/init_company \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"company_name": "Acme", "autonomy_level": 2}'
```

### 2. Start a sprint

```bash
curl -X POST http://localhost:8000/v1/start_sprint \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "company_id": 1,
    "sprint_name": "Sprint 1",
    "start_date": "2026-10-30",
    "scope_size": "M",
    "goal": "Ship the login screen",
    "backlog_items": [
      {"title": "Login form", "description": "Email and password, with the 72-byte cap"}
    ]
  }'
```

`scope_size` is `S` (up to 4 items), `M` (up to 8) or `L` (up to 12).

### 3. Let the agents work

`POST /v1/sprints/{sprint_id}/dispatch` sends the sprint through the
transactional outbox to NATS JetStream. The worker picks it up, calls the model
through the proxy, and hands the work to the daemon.

Watch it on `GET /v1/glassroom/stream?sprint_id=...&ticket=...`.

### 4. Feed the verification

This is the endpoint the whole design exists for. It takes the run and evidence
the backend did not get from the agent, and decides.

```bash
curl -X POST http://localhost:8000/v1/agent_runs/7/verify \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "company_id": 1,
    "evidence": {
      "expected": {"src/login.tsx": "<sha256 the backend computed from what it sent>"},
      "workspace_writes": [
        {"path": "src/login.tsx", "status": "written", "sha256": "<sha256 read back from disk>"}
      ],
      "ci": {"source": "GitHub Actions", "conclusion": "success", "ref": "head"},
      "test_run": {"command": "npm run test:run", "exit_code": 0}
    }
  }'
```

For a run whose `claims` are `{"files": ["src/login.tsx"], "tests": "ran
`npm run test:run`"}`, `artifact_size` 512 and `artifact_text` containing that
path, the response is:

```json
{
  "verdict": "verified",
  "checks": [
    {"name": "artifact_nonempty", "outcome": "pass",
     "observation": "artifact contains 512 bytes"},
    {"name": "claimed_files_present", "outcome": "pass",
     "observation": "all 1 claimed file paths appear in artifact"},
    {"name": "claimed_tests_evidenced", "outcome": "pass",
     "observation": "independent evidence from GitHub Actions reports success (head)"},
    {"name": "files_written", "outcome": "pass",
     "observation": "1 file(s) written: src/login.tsx"},
    {"name": "tests_run", "outcome": "pass",
     "observation": "`npm run test:run` passed"},
    {"name": "risk_tier", "outcome": "pass",
     "observation": "high — authentication: src/login.tsx",
     "tier": "high", "reasons": ["authentication: src/login.tsx"]}
  ]
}
```

That output is not hand-written: it comes from calling the checks with that run
and that evidence.

The two evidence keys that carry weight are the ones the agent cannot produce:

- **`ci`** answers a claim that tests pass. `conclusion: success` supports it,
  `failure` or `timed_out` refutes it, and no `ci` block leaves the claim
  `unverifiable` — an agent saying its tests passed is not evidence that they did.
- **`workspace_writes`** answers a claim that files were written. Each entry
  carries the hash the daemon read back from disk, and `expected` carries the one
  the backend computed from what it sent. A mismatch in either direction is a
  refutation, not a warning.

Three verdicts, not two:

- **`verified`** — every claim is supported.
- **`refuted`** — the evidence contradicts a claim.
- **`unverifiable`** — there is nothing to judge the claim against. It is a
  verdict of its own, not a soft pass: work nobody witnessed has not been shown.

`risk_tier` is a classification, not a verdict: its outcome is always `pass` and
the tier travels beside it, because deciding how much a delivery needs a person
is not the same as deciding whether it happened. See `services/risk.py`.

No model decides any of these. The checks are deterministic; see
[`ARCHITECTURE.md`](../ARCHITECTURE.md) and
`backend/app/services/verification.py`.

### 5. A person decides

```bash
curl -X POST http://localhost:8000/v1/agent_runs/7/approve \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"company_id": 1, "decision": "reject", "feedback": "The cap must count bytes, not characters"}'
```

The decision, the feedback and the rejection category are stored in
`AgentRunApproval` and signed in the audit log. The feedback reaches the agent
as a correction on the next attempt.

## Retired

`POST /v1/approve_task` was removed and answers **410 Gone**. Use
`POST /v1/agent_runs/{run_id}/approve`.

## Error codes

| Code | Meaning |
|---|---|
| 400 | Bad request |
| 401 | Missing or invalid token |
| 403 | Authenticated, not a member of that company, or role too low |
| 404 | Not found, or not visible to this caller |
| 409 | Conflict |
| 410 | Gone: the endpoint was retired |
| 413 | Payload too large: the artifact exceeds the size limit |
| 422 | Validation error |
| 429 | Rate limit exceeded |
| 500 | Internal error |
| 503 | Feature not configured (for example login before `JWT_SECRET_KEY`) |

## Rate limiting

100 requests per minute per client address (`RATE_LIMIT_DEFAULT`), in memory by
default (`RATE_LIMIT_STORAGE_URI`), so the counter is per process. Exceeding it
returns **429**.

No `X-RateLimit-*` headers are sent: `slowapi` is configured without
`headers_enabled`, so a client cannot read the remaining budget from the
response and has to handle 429 by retrying with backoff.
