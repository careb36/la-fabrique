# API Reference — La Fabrique

## Base URL

```
http://localhost:8000
```

## Authentication

Most endpoints require JWT authentication. Include the token in the Authorization header:

```
Authorization: Bearer <access_token>
```

### Obtaining a Token

1. Register a new user:
```bash
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass123", "full_name": "John Doe"}'
```

2. Login to get a token:
```bash
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepass123"}'
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

## Endpoints

### Health

#### GET /health
Health check endpoint (no authentication required).

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-10-17T12:00:00.000000"
}
```

---

### Authentication

#### POST /v1/auth/register
Register a new user account.

**Body:**
```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "full_name": "John Doe"  // optional
}
```

**Response:** `201 Created`
```json
{
  "user_id": 1,
  "email": "user@example.com"
}
```

#### POST /v1/auth/login
Authenticate and receive an access token.

**Body:**
```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Errors:**
- `401 Unauthorized` — Invalid email or password
- `503 Service Unavailable` — JWT_SECRET_KEY not configured

#### GET /v1/auth/me
Get current user profile (requires authentication).

**Response:** `200 OK`
```json
{
  "user_id": 1,
  "email": "user@example.com",
  "full_name": "John Doe",
  "memberships": [
    {
      "company_id": 1,
      "human_role": "Owner"
    }
  ]
}
```

---

### Companies

#### POST /v1/init_company
Create a new company (requires authentication).

**Body:**
```json
{
  "company_name": "My Company"
}
```

**Response:** `201 Created`
```json
{
  "company_id": 1,
  "company_name": "My Company"
}
```

---

### Sprints

#### POST /v1/start_sprint
Start a new sprint with a backlog.

**Body:**
```json
{
  "company_id": 1,
  "scope": "M",
  "backlog": [
    "Implement user authentication",
    "Add dashboard widgets",
    "Fix navigation bug"
  ]
}
```

**Scope options:**
- `S` — Small (max 4 items)
- `M` — Medium (max 8 items, default)
- `L` — Large (max 12 items)

**Response:** `200 OK`
```json
{
  "id": 1,
  "company_id": 1,
  "scope": "M",
  "status": "active",
  "backlog_items": [
    {"id": 1, "title": "Implement user authentication", "status": "todo"},
    {"id": 2, "title": "Add dashboard widgets", "status": "todo"},
    {"id": 3, "title": "Fix navigation bug", "status": "todo"}
  ]
}
```

---

### Agent Runs

#### POST /v1/agent_runs
Ingest an externally-produced agent run.

**Body:**
```json
{
  "company_id": 1,
  "external_ref": "github:owner/repo#123",
  "producer": "copilot",
  "artifact": "diff --git a/file.py b/file.py...",
  "claims": {
    "summary": "Implemented feature X",
    "body": "Detailed description of changes"
  }
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "created": true,
  "version": 1,
  "status": "ingested",
  "artifact_digest": "sha256:abc123..."
}
```

#### GET /v1/agent_runs
List agent runs for a company.

**Query Parameters:**
- `company_id` (required) — Company ID
- `producer` — Filter by producer (e.g., "copilot", "claude-code")
- `status` — Filter by status (e.g., "verified", "refuted")
- `limit` — Maximum results (default: 50)
- `since` — Filter by creation date (ISO 8601)
- `until` — Filter by creation date (ISO 8601)

**Response:** `200 OK`
```json
{
  "agent_runs": [
    {
      "id": 1,
      "external_ref": "github:owner/repo#123",
      "producer": "copilot",
      "status": "verified",
      "version": 1,
      "created_at": "2026-10-17T12:00:00Z"
    }
  ]
}
```

#### GET /v1/agent_runs/reviewer_record

How the Reviewer agent's suggestions (`REVIEWER_AGENT_ENABLED`) compared with
the decisions people recorded on the company's runs. A suggestion is stored on
the run (`suggested_decision`, `suggested_category`, `suggested_reason`,
`reviewed_by`, `reviewed_at`) apart from the approval; `reviewed_at` with no
decision means its answer was unusable. Requires Viewer.

**Query Parameters:**
- `company_id` — Company ID

**Response:** `200 OK`
```json
{
  "decided": 4,
  "agent_agreed": 3,
  "agent_unusable": 1,
  "verifier_called": 2,
  "verifier_agreed": 2
}
```

`verifier_called` counts the decided runs whose latest verification was
`verified` or `refuted` (the verdict alone would approve or reject them), and
`verifier_agreed` how many of those the person decided the same way: the
baseline the agent has to beat.

#### POST /v1/agent_runs/{run_id}/verify
Verify an agent run's claims against evidence.

**Body:**
```json
{
  "company_id": 1,
  "evidence": {
    "ci": {
      "conclusion": "success",
      "source": "github-check-run",
      "ref": "run/12345"
    }
  }
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "verdict": "verified",
  "checks": [
    {"name": "artifact_nonempty", "outcome": "pass", "observation": "..."},
    {"name": "claimed_files_present", "outcome": "pass", "observation": "..."},
    {"name": "claimed_tests_evidenced", "outcome": "pass", "observation": "..."}
  ]
}
```

**Verdicts:**
- `verified` — All checks passed
- `refuted` — At least one check failed
- `unverifiable` — Insufficient evidence to verify or refute

---

### GitHub Integration

#### POST /v1/integrations/github/bindings
Bind a GitHub repository to a company.

**Body:**
```json
{
  "company_id": 1,
  "owner": "myorg",
  "repo": "myrepo",
  "webhook_secret": "my-secret",
  "inclusion_rule": "all"
}
```

**Inclusion rules:**
- `all` — Ingest all PRs
- `bots_only` — Only bot-authored PRs
- `non_bots` — Only human-authored PRs

#### POST /v1/integrations/github/backfill
Backfill historical PRs from a repository.

**Body:**
```json
{
  "company_id": 1,
  "owner": "myorg",
  "repo": "myrepo"
}
```

**Response:** `200 OK`
```json
{
  "ingested": 5,
  "skipped": 2,
  "errors": []
}
```

---

### Memory

#### GET /v1/memory/search
Semantic search over stored memories.

**Query Parameters:**
- `company_id` — Company ID
- `query` — Search query
- `limit` — Maximum results (default: 10, between 1 and 100; anything else is a 422)

**Response:** `200 OK`
```json
{
  "results": [
    {
      "id": 1,
      "content": "Previous decision about...",
      "score": 0.95
    }
  ]
}
```

#### POST /v1/memory/store
Store content in vector memory.

**Body:**
```json
{
  "company_id": 1,
  "content": "This is important information to remember",
  "metadata": {"source": "sprint-1"}
}
```

---

### GlassRoom (SSE)

#### GET /v1/glassroom/stream
Server-Sent Events stream for real-time sprint events.

**Query Parameters:**
- `sprint_id` — Sprint ID to subscribe to
- `ticket` — required when authentication is on: a five-minute ticket for this
  sprint from `POST /v1/sprints/{id}/stream_ticket` (Viewer of the sprint's
  company). A browser EventSource cannot send an Authorization header, so the
  stream takes this instead; the holder's membership is checked again on use.

**Event Types:**
- `status` — Sprint status change
- `agent_start` — Agent started working
- `message` — Agent message
- `agent_complete` — Agent finished
- `error` — Error occurred
- `needs_split` — Sprint needs to be split

**Example:**
```
event: message
data: {"agent": "Developer", "message": "Working on task #1..."}

event: agent_complete
data: {"agent": "Developer", "task_id": 1}
```

---

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request — Invalid input |
| 401 | Unauthorized — Missing or invalid token |
| 403 | Forbidden — Insufficient permissions |
| 404 | Not Found — Resource doesn't exist |
| 409 | Conflict — Resource already exists |
| 413 | Payload Too Large — Artifact exceeds size limit |
| 422 | Validation Error — Invalid request body |
| 429 | Too Many Requests — Rate limit exceeded |
| 500 | Internal Server Error |
| 503 | Service Unavailable — Feature not configured |

---

## Rate Limiting

- Default: 100 requests per minute per IP
- Headers included in all responses:
  - `X-RateLimit-Limit` — Request limit
  - `X-RateLimit-Remaining` — Remaining requests
  - `X-RateLimit-Reset` — Reset timestamp
