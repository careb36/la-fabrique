# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

**La Fabrique** is an AI-powered autonomous software development platform. It orchestrates a multi-agent team (PO, Architect, ScrumMaster, Developer, QA, SecOps, TechWriter) using LangGraph to execute software sprints — from backlog to code generation and execution — inside a user's VS Code workspace.

> **Direction adopted (2026-09-19).** The repositioning in
> [`docs/POSITIONING.md`](docs/POSITIONING.md), tracked in issue #38, is the
> project's direction: the agents become interchangeable producers, and the
> product becomes the layer that verifies their work and records evidence. The
> description above still reflects what the code does today, not where it is
> going. Read the positioning document before planning new work, and note the
> design rules in it — in particular that a
> claim and an observation must never share a field, that an agent's report of
> its own test run is a claim rather than an observation, and that hashes and
> signatures are never accepted from the party being recorded.
>
> **Amendment (2026-10-18).** The factory manages itself as a company of AI
> agents that follow procedures, talk to each other and learn from
> retrospectives. The evidence keeps the last word: messages between agents are
> claims, and procedure changes are kept or reverted by deterministic metrics.
> See the amendment at the end of `docs/POSITIONING.md` for the design and the
> order of work.

## Running the System

```bash
# Full stack (preferred)
docker compose up -d

# Individual services
docker compose up backend -d
docker compose up frontend -d
docker compose up llm-proxy -d

# Workspace daemon: runs natively on the computer that holds your projects
./scripts/start-daemon.sh        # macOS / Linux
.\scripts\start-daemon.ps1       # Windows (PowerShell)
```

The daemon is the only component that touches the user's files, so the folder
chosen in "New company" is a path on that computer (`/Users/ana/code/app`,
`/home/ana/src/app`, `C:\Users\ana\source\repos\app`). The backend never needs
to see the user's disk; `docker compose --profile docker-daemon up` is an
opt-in Linux-only alternative that mounts `PROJECTS_ROOT` instead.

- Backend API: `http://localhost:8000` — OpenAPI docs at `/docs`
- Frontend: `http://localhost:5173` (Vite dev) or `http://localhost:3000` (production)
- LLM Proxy: `http://localhost:5100`

**Frontend dev server (hot reload):**
```bash
cd frontend && npm install && npm run dev
```

**Frontend production build:**
```bash
cd frontend && npm run build
```

## Required Environment Variables

Copy `.env.example` to `.env` and fill in:
- `GEMINI_API_KEY` — Google AI Studio key (used by Architect/PO agents)
- `DEEPSEEK_API_KEY` — DeepSeek key (used by Developer/QA agents)
- `POSTGRES_PASSWORD`, `NEO4J_PASSWORD` — database credentials
- `NEO4J_AUTH=neo4j/<password>` must match `NEO4J_PASSWORD`
- `FERNET_SECRET_KEY` — optional. Encrypts `ProjectCredential.encrypted_value`
  at rest. Without it those values are stored with a `plaintext:` prefix and the
  backend warns at startup. Generate one with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `JWT_SECRET_KEY` — required for authentication. Login returns 503 until configured.
  Generate with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `AUTH_REQUIRED` — set to `true` to enforce authentication on sensitive routes
- `SUPPORT_ADMIN_EMAILS` — optional, comma-separated account emails. Those users
  see and triage every support ticket and download the support logs (`/support`
  in the frontend, flagged by `support_admin` in `/v1/auth/me`); everyone else
  sees only the tickets reported with their account email.
- `SUPPORT_AGENT_ENABLED` — optional, default `false`. The Support agent
  (`services/support_agent.py`) triages new help-desk tickets every
  `SUPPORT_AGENT_INTERVAL_SECONDS` (60): a suggested severity and category,
  stored beside what the reporter chose, and a first reply the reporter sees.
  Off by default because reporting a bug is public and each ticket costs an
  LLM call. A support admin decides a ticket's severity and category in the
  help desk; the decision is stored apart from the reporter's choice and the
  agent's suggestion (`decided_*`, stamped with who changed it only when it
  changes; an empty value clears it), `GET /v1/support/agent_record` counts
  how often the agent's suggestions matched it (its unusable answers count as
  misses, and are counted) beside how often the reporters' own choices did
  (only where a reporter chose: the form presets no impact and asks for no
  category, so neither is made up), and those numbers go into the agent's
  next prompt.
- `REVIEWER_AGENT_ENABLED` — optional, default `false`. The Reviewer agent
  (`services/reviewer_agent.py`) reads the evidence of each run another
  producer sent that waits for a person (the Verifier's checks, the claims,
  the artifact as data) every `REVIEWER_AGENT_INTERVAL_SECONDS` (60) and
  suggests the decision in a fixed format: approve or reject, a category and
  a reason, stored on the run (`suggested_*`, `reviewed_by`) apart from the
  approval a Manager records; an unusable answer leaves the run to people.
  `GET /v1/agent_runs/reviewer_record` counts how often its suggestions
  matched the decisions (unusable answers as misses) beside how often the
  Verifier's verdict alone would have (verified → approved, refuted →
  rejected), and those numbers go into its next prompt. Off by default: each
  run costs an LLM call.
- `PUBLIC_API_URL` — optional. The address GitHub uses to reach the backend
  (public host or tunnel). `/v1/capabilities` reports it as `public_api_url` and
  the GitHub page shows it as the webhook Payload URL.
- `AUDIT_SIGNING_KEY` — optional. Signs audit rows with HMAC-SHA256, and keys
  each company's audit hash chain (`audit_chain.py`: every company row carries
  `chain_seq`, `prev_hash` and `chain_hash`; `GET /v1/audit/chain` shows where
  a deleted, inserted, reordered, altered or moved row breaks it). Without a
  key the chain is unkeyed and says so.
  Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
- `VOICE_API_KEY` — optional. The shared key the desktop assistant sends as
  `X-Voice-Key` to `/v1/voice/*` (`routers/voice.py`, actions in
  `routers/voice_actions.py`) and to `POST /v1/auth/desktop`, which trades it
  for a session of the desktop operator (an Owner of the oldest company).
  Unset, those routes answer 503 while `AUTH_REQUIRED` is on and the desktop
  exchange refuses; they never open anonymously. `VOICE_COMPANY_ID` picks the
  company when the assistant names none (empty: the oldest).
- `FABRICA_BUILDS_DIR` — where `POST /v1/voice/build` (`routers/build.py`,
  `services/codegen.py`) writes a project asked for in one sentence, served
  back sandboxed under `/v1/voice/build/<slug>/<file>`; default
  `/workspace/builds`.
- `NVIDIA_API_KEY` / `NVIDIA_PROXY_URL` — optional. NVIDIA's own gateway for
  the same `nvidia/` ids Nebius serves; the proxy tries it first when its key
  is set. `AGENT_MODEL` is the model of every role `NEMOTRON_ROLES` does not
  name. `NEO4J_DISABLED=true` skips Neo4j on an install without it.
- `NATS_BIND` — optional, default `127.0.0.1`. The host address NATS listens on;
  the workspace daemon on this computer connects there. `0.0.0.0` exposes it to
  other machines, which can then ask the daemon to run commands.
- `PROJECTS_ROOT` — only for the optional Linux daemon container (`--profile
  docker-daemon`): the host folder holding your projects, mounted at the same path.
- `DELIVERY_TESTS_ENABLED` — optional, default `false`. After an agent's files are
  written, the daemon runs the project's tests (`DELIVERY_TEST_COMMAND`, or detected
  `npm test` / `pytest`) and the exit status is recorded as evidence; a failing run
  sends the task back for rework. It executes agent-written code on the daemon's machine.

## Architecture Overview

```
React Frontend (Vite + TypeScript + TailwindCSS)
        ↓ REST / SSE
FastAPI Backend  ←→  LangGraph Agent Orchestration
        ↓                   ↓
    Postgres           NATS JetStream (pubsub)
    (pgvector)               ↓
    Neo4j             VS Code Daemon
    (knowledge graph)  (writes files, runs shell)
         ↓
    LLM Proxy (Flask, port 5100)
         ↓ ↓
    Gemini API    DeepSeek API
```

### Key Components

**`backend/app/main.py`** — The FastAPI app: lifespan (workers, JetStream, schema backfills), middleware and the routers it includes. The routes live in `backend/app/routers/` (`sprint`, `agents`, `agent_runs`, `inbox`, `messages`, `procedures`, `support`, `workspace`, `github`, `auth`, `enterprise`, `voice`, `build`). When `frontend/dist` exists the backend also serves the web UI same-origin (`ui_static.py`); the frontend's API base defaults to its own origin (`frontend/src/lib/apiBase.ts`), the Vite dev server proxies `/v1` to `VITE_PROXY_TARGET`, and `VITE_API_URL` still wins.

**`backend/agents/graph.py`** — Optional LangGraph producer, disabled unless `AGENT_GRAPH_ENABLED=true`. Its runs are ingested as `AgentRun` records with `producer: "le-fabrique-graph"`.

**`backend/app/llm_proxy_client.py`** — Thin HTTP client wrapping the LLM proxy for token-budget-aware requests. `chat()` / `chat_async()` take a `model` id (default `"gemini-pro"`), a `role`, and an optional `bu_id`.

**`llm-proxy/app.py`** — Flask gateway that enforces per-company token budgets, routes by model-id prefix to the wired providers (NVIDIA's gateway, Nebius Token Factory, Gemini, DeepSeek, Qwen), checks every id against the provider's live catalogue before sending it, and refreshes each provider's catalogue hourly. Each answer says how its token count is known (`llm-proxy/usage.py`): `usage_status: reported` with the provider's figure in `usage`, or `estimated` with a characters/4 estimate apart in `usage_estimate` (charged to the quota, never shown as usage); the backend's `usage_status` keeps estimates out of the KPI averages.

**`vscode-daemon/daemon.py`** — The workspace daemon: a Python process that runs natively on the user's macOS, Linux or Windows machine (started by `scripts/start-daemon.*`, reconnects to NATS on its own). It answers `workspace.generate` (write files, reply with the sha256 read back from disk), `workspace.execute` (run a command), `workspace.capabilities`, `workspace.status`, `workspace.browse` (folder picker) and `workspace.inspect` (canonical path, git remote/branch, file snapshot for stack detection), and consumes the JetStream queue `workspace.deliver` for files queued while it was offline, reporting on `workspace.delivered`. Its `requirements.txt` is `nats-py` only.

**`backend/app/routers/workspace.py`** / **`services/workspace_daemon.py`** — `GET /v1/workspace/{status,browse,inspect}` relay the picker and project check to the daemon (503 with start instructions when none is connected). `status` reports `state`: `connected`, `absent` (NATS says nothing listens) or `unknown` (NATS unreachable, no answer in time, or an error reply), with a `reason`; unknown is never shown as stopped. `POST /v1/discover_team` inspects the folder through the daemon and runs stack detection on its file snapshot (`materialized_snapshot`), recording the host path.

**`backend/app/services/board.py`** — The pure readers of a task's comment thread, shared by the task worker, `routers/inbox.py` and `services/carry_over.py`: which comment is the deliverable to review, the pending `NEEDS WORK:` requests, whether a blocked task waits for a person (`blocked_item_next_step`, `item_is_settled`) and its `block_reason`. No engine, no I/O; the gate author names (`Quality gate`, `Verifier`) live here too. The advice a task got (the worker's console-advice note, the Architect's `ARCHITECT_CONSULTED:` brief) is never a verdict, and the phrases that keep a task blocked count only from the system, a gate or a person (`BLOCK_VERDICT_AUTHORS`), never from a deliverable.

**`backend/app/services/console_assistants.py`** — The terminal assistants the daemon can run (GitHub Copilot CLI, Claude CLI): which ones to ask for a task (`select_assistants`), the command with the prompt shell-quoted, `collect_advice` through `workspace.execute`, and the per-company cooldown persisted in `AssistantRuntimeState` when one is out of quota or missing on the host. Their advice is prompt context and a board note, never evidence; `GET /v1/sprints` counts tasks with and without it (`console_advice`: done and rework per group), so the Sprints page shows whether it helps. The Architect's briefs are counted the same way (`architect_advice`, rework from the first brief on), and `services/architect.py` tells the Architect, when it is asked again, how the company's briefed tasks went in its completed sprints against the rest. `services/glassroom.py` holds `publish_glassroom`, the best-effort publisher every worker uses for the sprint's SSE stream.

**`backend/app/nats_client.py`** — `enable_jetstream()` declares the work-queue streams in `DURABLE_STREAMS` (`task.assign`, `workspace.deliver`, `workspace.delivered`); `publish()` stores durable subjects with a `Nats-Msg-Id`, `consume()` is a durable pull consumer with explicit acks. Without JetStream both fall back to core NATS with a warning; `/health` reports `jetstream`.

**`frontend/src/`** — React 18 app. Key views:
- `KanbanBoard` — sprint task tracking with drag-and-drop (`@dnd-kit`)
- `GlassRoom` — real-time agent activity monitor via SSE
- `SprintWorkspace` — sprint creation and management
- `SupportBot` — bilingual (EN/ES) built-in help desk chat

**`backend/janitor/main.py`** — Background maintenance container (runs daily). Cleans outbox events and rebuilds pgvector indices with `REINDEX CONCURRENTLY`.

### Data Flow for a Sprint

Tasks are executed by the **task worker** (`backend/app/services/task_worker.py`);
the LangGraph graph is only an optional kickoff conversation.

1. `POST /v1/start_sprint` writes the sprint, one `BacklogItem` per task and one
   outbox event per task on `task.assign`; the outbox processor stores them in the
   JetStream stream `FABRIQUE_TASKS` (an outbox row completes only once stored).
2. The task worker consumes `task.assign` as the durable consumer `task-worker`,
   so assignments published while it was down are processed when it starts. It
   loads the item and the assigned agent
   (empty model → role default from `llm/model_factory.py`) and calls the LLM proxy.
   The prompt asks for every file as a fenced block with `path=<relative path>`;
   on rework it also carries the pending `NEEDS WORK:` feedback. It also carries
   the company's past decisions from memory (scoped by `company_id`), and
   **Lessons from Recent Sprints**: the retrospective counts and the review
   requests from the company's last two completed sprints, read from the board
   (`_load_recent_lessons`), and the **Company Procedures** in force for the
   agent's role (QA's go into its review prompt).
3. `parse_file_manifest` turns the answer into files. The worker sends them to the
   VS Code daemon with a NATS **request** on `workspace.generate`, targeting the
   company's project (`ProjectDiscovery.project_path`, recorded at company creation;
   `AGENT_WORKSPACE_ROOT` is the fallback). The daemon replies per file with the
   sha256 of the bytes it read back from disk. If no daemon answers, the files are
   queued on `workspace.deliver` (JetStream), the run is recorded as waiting for
   that job and the review loop holds the task; when a daemon connects it writes
   them and reports on `workspace.delivered`, and the run is re-verified against
   the hashes the backend recorded (`_on_delivery_result`).
4. Optionally (`DELIVERY_TESTS_ENABLED`) the daemon runs the project's tests via
   `workspace.execute` and returns the exit status.
5. The deliverable is ingested as an `AgentRun` (`producer: le-fabrique-task-worker`,
   `external_ref: task-<id>`) and verified deterministically (`files_written`,
   `tests_run`, …). Claims (declared files, the agent's summary) and observations
   (daemon reports) are kept apart; the board and Glassroom show the verdict.
6. The review loop sends a refuted/unconfirmed delivery or a failed test run back
   for rework without asking an LLM; otherwise QA reviews, and only an explicit
   `APPROVED:` closes the task. The Verifier also records a `risk_tier` check
   (`services/risk.py`: high for authentication, secrets, payments or the CI
   pipeline, medium for shell scripts, migrations, dependency manifests or
   container files, from the paths the daemon wrote and the producer declared;
   a producer may raise it with a reason, never lower it). An approved task
   whose tier is high waits for a person at every autonomy level, level 3
   included: the inbox lists it with `risk_hold`, a Manager accepts it (marks
   it done) or sends it back, and it counts neither as blocked in the
   procedures' numbers nor as a task to carry over on the company's own. Before any of that, the text checks on the
   deliverable (length, sections, balanced fences — `_validate_minimum_deliverable`)
   send it back with the reason as `Quality gate`, up to
   `AUTOPILOT_MAX_REWORK_CYCLES`, then block the task and escalate to the
   ScrumMaster. A sprint closes when every task is settled: done, or blocked
   until a person acts (nothing the worker retries, re-reviews or an operator
   froze). Blocked tasks stay on the board, appear in the retrospective and
   count in the procedures' `blocked_rate`; approvals close the sprint on the
   spot and the review cycle closes one whose last open task got blocked.
   `GET /v1/inbox` (Viewer, `routers/inbox.py`) lists what the company needs a
   person for: the tasks blocked until someone acts (not the ones the worker
   still retries or re-reviews), the procedure proposals waiting and how many
   runs of other producers nobody decided on (the company's own task worker
   and kickoff runs, `IN_HOUSE_PRODUCERS`, are decided by the review loop;
   `GET /v1/agent_runs?exclude_in_house=true` lists the rest; with
   `REVIEWER_AGENT_ENABLED` the Reviewer agent suggests a decision on each,
   kept on the run apart from the approval). The Review page shows them (a Manager can send a
   blocked task back to work, with how earlier second attempts went beside them) and the navigation counts them. A blocked task
   can also get another attempt in the next sprint (`services/carry_over.py`):
   `POST /v1/start_sprint` takes `carry_over_ids` (counted in the scope), the
   "Plan a sprint" form offers them (with how earlier second attempts went,
   from the sprint list's `second_attempts`), and with `autonomy_level` 3 the follow-up
   sprint carries the closed sprint's blocked tasks on its own, once each. The
   new task carries what blocked the old one (a `Previous attempt` prompt
   section); the old one is marked and leaves the inbox. The escalation gets
   an answer (`services/scrum_master.py`): the ScrumMaster reads what blocked
   the task, the rework asked for and how the company's second attempts went
   (`track_record`: done out of carried, with and without its brief, counted
   from the boards of completed sprints, the same numbers the Sprints page
   shows) and decides, in a fixed `DECISION … END`
   format a parser checks, between another attempt with a brief for it or
   leaving it to a person. The decision is a `decision` message that names
   the escalation it answers (written by the worker, not the model), a claim: the
   inbox shows it as `triage`, the brief travels with the carried task into
   its prompt (and into QA's review prompt, so the second attempt is judged
   against the same context), and a task left for a person is not carried
   over on the company's own (a person still can). No usable answer keeps
   the default.
   Every question to the ScrumMaster (the triage, the procedure proposals)
   goes through `scrum_master.ask`, and every count of rework requests
   (the sprint list, the procedures' numbers) through
   `board.rework_request_count`.
7. Each hand-over between roles is also recorded as an `AgentMessage`
   (`agent_messages`), the company's conversation:
   - the Developer's question to the Architect and its answer (the Architect
     is told how tasks went after its earlier briefs, counted from the boards);
   - the handoff to QA, listing the declared files;
   - QA's decision or rework request, and the Verifier's;
   - escalations to the ScrumMaster when a task is blocked;
   - the ScrumMaster's retrospective to the team when a sprint closes.

   Messages are claims: comments still drive the review loop, and the evidence
   decides. `GET /v1/messages` (Viewer; filters `sprint_id`, `backlog_item_id`,
   `kind`) feeds the sprint's Conversation tab and the task page.
8. When a sprint closes, procedures are measured and proposed
   (`services/procedures.py`):
   - Each active procedure with two completed sprints since its adoption is
     kept, or reverted if rework per task or the share of blocked tasks got
     clearly worse. A reverted procedure brings back the version it replaced.
   - After a sprint with rework or blocked tasks, the ScrumMaster proposes up to
     two procedures in a fixed `PROCEDURE … END` format; anything else is
     ignored. With `autonomy_level` 3 a proposal is adopted at once; otherwise
     a Manager adopts or rejects it (`/v1/procedures`, the Procedures page).
     The ScrumMaster is shown what earlier procedures did (kept, reverted or
     unmeasured with the board's numbers, or rejected by a person;
     `procedures.history_prompt`), and a proposal with the same text as one
     reverted or rejected is dropped (`propose(skip_failed=True)`); a Manager
     writing a procedure can still bring one back.
   - Adoption records the numbers of the last two completed sprints as the
     baseline. Outcomes and proposals are posted to the team as `proposal`
     messages. The numbers decide, never a model.
9. With `AGENT_GRAPH_ENABLED=true`, `agent_worker` also runs the graph kickoff for
   the sprint; its transcript is ingested as an `AgentRun` (`le-fabrique-graph`).
   A failed kickoff never blocks the sprint.
10. Engram events go to Neo4j for episodic memory; embeddings to pgvector for RAG.

### Memory Architecture

- **pgvector (Postgres)** — RAG short-term semantic memory. Used for code snippet retrieval and context injection. API: `GET /v1/memory/search`, `POST /v1/memory/store`
- **Neo4j** — Temporal knowledge graph. Immutable "Engram" nodes record every agent decision with timestamps. Used for lineage, compliance, and cross-sprint learning. Queried via APOC plugin.

### Auth & Multi-tenancy

- Company-scoped: all data (agents, sprints, memory, budgets) is namespaced by `company_id`
- RBAC covers both human roles (manager, developer) and AI agent roles (PO, Architect, etc.)
- Passwords hashed with bcrypt directly (`backend/app/passwords.py`); the schema rejects a password over bcrypt's 72-byte limit, and login re-hashes a stored hash whose cost is below the current one. `POST /v1/auth/login` issues an HS256 JWT (`JWT_SECRET_KEY`); `auth_deps.get_current_user` resolves it. Authentication enforcement is on by default; set `AUTH_REQUIRED=false` only for a local demo without a login. Configure `JWT_SECRET_KEY`, then register and log in through the frontend. Protected routes require a JWT and company roles follow Owner > Manager > Viewer. A company's agents (`/v1/agents`) and its token usage are read by its Viewers; only its Managers create, change or delete an agent, since its prompt, model and budget decide what it does (the agents page is read-only for a Viewer). Likewise only a Manager records the folder a company's agents write to (`POST /v1/discover_team` with a `company_id`; the New company wizard calls it without one), and `/v1/generate` bills only a business unit of the company itself; a sprint's token total counts only its own company's audit rows. Company initialization creates the caller's Owner membership; invitations require Owner, and inviting an existing member is a 409.
- Always public: `/health`, registration/login, the HMAC-signed GitHub webhook, support bug reporting/chat, `/v1/models`, `/v1/capabilities` (feature flags only, no company data), and the retired `/v1/approve_task` (410). Glassroom SSE cannot take an Authorization header (EventSource sends none): with `AUTH_REQUIRED` it takes a five-minute `ticket` for one sprint from `POST /v1/sprints/{id}/stream_ticket` (Viewer), and checks the holder's membership again when it is used; the frontend asks for a new one on every connection. `/v1/auth/me` always requires a JWT. Audit writes and memory stores resolve company ownership from authorized membership and existing interactions, never payload metadata; callers with multiple memberships should select a `company_id` query parameter. Audit verification, memory search, and lineage use column-backed Viewer scoping. Legacy NULL-company evidence is flagged and included only without a company filter (authenticated when `AUTH_REQUIRED=true`). Startup backfills historical company metadata into the audit/vector columns and Neo4j properties. Help-desk tickets are not company data: support admins (`SUPPORT_ADMIN_EMAILS`) see and update all of them and download the logs; other authenticated users see only their own (matched by account email, 403 for another reporter, 404 for another's ticket). With `AUTH_REQUIRED=false` and no token, the desk stays open as in a local demo. When `SUPPORT_AGENT_ENABLED`, the Support agent triages open tickets first (`suggested_severity`, `suggested_category`, `agent_reply`, `triaged_by`), and a support admin decides.

## Test Suite

The backend has a pytest test suite under `backend/tests/`.  No external services (Postgres, NATS, Neo4j, LLM proxy) are required — every boundary is stubbed with an in-memory SQLite engine or `unittest.mock`.

```bash
# Run all backend tests (fast, DB-free)
cd backend && PYTHONPATH=.:app python3 -m pytest tests -q
```

Test files:

| File | What it covers |
|------|----------------|
| `test_glassroom_sse.py` | SSE fan-out and stream ordering; the replayed history carries the same event ids on every connection, so a reconnecting client can tell it from new events |
| `test_orchestration_metrics.py` | Orchestration metric helpers |
| `test_start_sprint.py` | `POST /v1/start_sprint` — happy path, validation, outbox events |
| `test_graph.py` | LangGraph node compilation, routing helpers, `_invoke_agent` events |
| `test_needs_split.py` | `_mark_sprint_needs_split` and `_complete_sprint_and_plan_follow_up` |
| `test_model_factory.py` | Role-to-model map and business-unit header propagation |
| `test_crypto.py` | Fernet credential encryption: round trip, tamper and wrong-key rejection, keyless fallback, legacy rows |
| `test_llm_routing.py` | Task worker: empty agent model → role default from `model_factory`, LLM failures on the board, `served_model` on the AgentRun |
| `test_task_delivery.py` | File manifest parsing, delivery to the real daemon against `tmp_path`, sha256 `files_written` check, daemon-down → unverifiable |
| `test_delivery_tests.py` | Opt-in post-delivery test run: command detection, `tests_run` check, passing/failing suites through the real daemon |
| `test_review_gate.py` | Review loop: delivery gate before QA, explicit `APPROVED:` verdict, rework limit, company-scoped evidence |
| `test_board.py` | Reading a task's comment thread: carry-over notes and the console-advice note are never a verdict (an assistant's "retry" or "manual triage" moves nothing), pending rework survives gate verdicts and send-backs, rework budgets restart after a send-back, only the worker's note marks a task as advised and its rework counts from that note on; the Architect's brief is never a verdict either, a deliverable's words are not a block reason, and a briefed task's rework counts from the brief on |
| `test_risk_tier.py` | The risk tier: each area a path marks, look-alike words left low, the highest path decides, a producer raises but never lowers it, the Verifier's check never decides the verdict; an approved high-risk task waits for a person at autonomy 3, settles the sprint, is listed as `risk_hold`, is not a failure in the procedures' numbers and is not carried over on the company's own |
| `test_history_check.py` | The independent checker of task histories (`app/history_check.py`): done needs an approval or a person, an approval needs a deliverable before it and a verified latest run (unless a person closed it), a high-risk hold closes only through a person, a task is carried over once, a ScrumMaster decision answers an escalation of its own task; the database is read the same way, and the checker imports none of the production readers |
| `test_sprint_close.py` | A sprint closes when every task is settled (blocked for a person counts; retries, re-reviews and freezes keep it open); the pre-review quality gate asks for rework with the reason, then blocks and escalates |
| `test_inbox.py` | `GET /v1/inbox`: tasks blocked for a person (frozen included, retries excluded), proposals waiting, undecided runs, company scoping |
| `test_carry_over.py` | A blocked task carried into the next sprint: `carry_over_ids` on `start_sprint`, the reason in the new task and its prompt, refusals (404/409, scope), the original leaves the inbox, the autonomy-3 follow-up carries once |
| `test_scrum_master.py` | The ScrumMaster's triage of an escalation: the prompt, the fixed answer format, the decision recorded and read back, nothing recorded without a usable answer, the brief in the next attempt, a task left for a person not carried on the company's own, the second-attempt track record in the prompt, a send-back during the triage window makes the answer stale, a decision names the escalation it answers and is judged by it, `END` with a period or Windows line endings |
| `test_database_timezone.py` | The Postgres session is pinned to UTC, so aware datetimes in `timestamp` columns and the naive UTC text in board comments stay comparable |
| `test_backlog_comments.py` | In-place appends to `BacklogItem.comments` are persisted |
| `test_kickoff_failure.py` | A failed graph kickoff leaves the sprint active and its tasks running |
| `test_nats_connect_retry.py` | NATS connect backoff; workers start once connected |
| `test_console_capabilities.py` / `test_daemon_capabilities.py` | `workspace.capabilities` probe and daemon handler; assistants skipped when absent |
| `test_console_assistants.py` | Which assistants a task gets, the prompt quoted into the command, persisted quota and missing-binary cooldowns, and the full path with its Glassroom telemetry |
| `test_sprint_list.py` | `GET /v1/sprints`: progress, blocked and rework counts per sprint, second attempts (done, and briefed by the ScrumMaster), tasks with and without console advice and the Architect's brief, ordering, membership scoping |
| `test_architect.py` | The Architect's record: briefed tasks against the rest over the company's completed sprints, rework from the brief on, and that record in its next consultation prompt |
| `test_agent_runs.py` | AgentRun ingest, verification, `external_ref` and `sprint_id` filters |
| `test_jetstream_durability.py` | JetStream publish/consume/ack and core fallback; deliveries queued for an offline daemon, held by the gate, verified from the daemon's report |
| `test_agent_messages.py` | The conversation between roles: messages at each hand-over, escalation and retrospective; `GET /v1/messages` scoping and filters |
| `test_procedures.py` | Proposal parsing, versions and supersession, baseline at adoption, keep / revert / unmeasured after two sprints, ScrumMaster proposals by autonomy level, what earlier procedures did in the proposal prompt, a reverted or rejected text not proposed again (a person still can), procedures in prompts, `/v1/procedures` |
| `test_memory_lessons.py` | Company-scoped memory search, retrospectives visible to every role, lessons from the last completed sprints in the task prompt |
| `test_support_agent.py` | Support agent triage: fixed answer format, suggestions beside the reporter's choice, unusable answers left to people, failed calls retried, reply visible to the reporter; its record against the admins' decisions (unusable answers as misses, beside the reporters who chose a value, legacy rows compared case-blind) and that record in its next prompt |
| `test_reviewer_agent.py` | The Reviewer agent: fixed answer format, the prompt treats the run as data and carries the Verifier's checks, a suggestion stored on an outside producer's run beside no approval (in-house and decided runs skipped), unusable answers left to people, failed calls retried; its record against the decisions people recorded, with the Verifier's verdict as the baseline, company-scoped, and in its next prompt |
| `test_support_access.py` | Support admins versus reporters on tickets and logs, `support_admin` in `/v1/auth/me`, 409 when re-inviting a member; an admin's severity and category decision stored apart, credited to whoever changed it and clearable, unknown values refused, `/v1/support/agent_record` admin-only; the reporter's values normalized and no severity or category made up; the Impact filter reads the decision first, else the reporter's choice; `resolved_at` is when the ticket was resolved, kept by later saves and cleared on reopening |
| `test_agent_access.py` | A company's agents and token usage: 401 without a token, 403 outside the company, a Viewer reads but cannot create, change or delete, a Manager can |
| `test_cross_company_access.py` | Only a Manager sets where a company's agents write (`discover_team`), `/v1/generate` bills only the company's own business unit, a sprint's tokens are its own company's |
| `test_glassroom_access.py` | The Glassroom stream with authentication required: a sprint-scoped ticket for a Viewer, refused without one, with an access token, another sprint's or an expired one, and once its holder left the company |
| `test_workspace_host.py` | Daemon folder browsing, git remote/branch inspection, snapshots, Windows shell/roots; `/v1/workspace/*` relay and discovery through the daemon |
| `test_audit_chain.py` | The audit hash chain per company: numbered and linked rows, each company its own chain, a deleted, altered or moved row breaks it where it was, a chain rewritten without the key does not verify, unkeyed chains say so, rows without a company stay unchained, KPI turn rows are signed and chained too |
| `test_tenant_scoping.py` | Every table carries a required `company_id` that references `companies`, or is listed with its reason (the tenant, users, help-desk tickets, the outbox, backlog items through their sprint); `audit_log` alone may hold rows without a company; the lists hold no stale names |
| `test_exception_handlers.py` | The catch-all 500: it says a report was sent only when the support webhook took it, names the installation from `FABRIQUE_VENDOR_ID`, and publishes the incident ticket on NATS |
| `test_voice_control.py` / `test_voice_build.py` | The voice façade: the shared key or a real user, never anonymous; each spoken action calls the same endpoint as the web; a voice-created sprint starts paused; a project from one sentence is written inside `FABRICA_BUILDS_DIR` and served sandboxed; an empty `VOICE_COMPANY_ID` is unset |
| `test_auth_desktop.py` / `test_ui_static.py` | The desktop session exchange (refused without the key); the built UI served same-origin without swallowing API routes |
| `test_metrics.py` | `/metrics` labels requests by route template, a fixed route by its path, a CORS preflight as `preflight` and a path no route answered as `unmatched`; memory search caps its `limit` |

**End to end, against a real stack:** `scripts/e2e/run.sh` starts the backend,
the workspace daemon and a fake LLM proxy (`scripts/e2e/fake_llm.py`,
deterministic answers) against a Postgres and a NATS you provide
(`docker compose up -d postgres nats`, or a local pair via `E2E_POSTGRES_*`
and `E2E_NATS_URL`; the e2e database is recreated on every run), then drives
one company through the loop and checks it through the API (a fake Copilot
CLI, `e2e-copilot`, on the daemon's PATH advises every task, so the
console-assistant path runs too): the foundation
sprint closes with its task blocked for a person after two rework requests,
the ScrumMaster's triage of it, the retrospective and an adopted procedure;
the inbox lists the task;
`start_sprint` with `carry_over_ids` retries it beside a new task whose
files are written and verified; both tasks were advised and the advice reached their prompts; the sprint list counts the retry as a briefed second attempt; the inbox then lists only the new attempt;
a person carries that attempt into a third sprint, where it blocks again and
the ScrumMaster's triage is told how the company's second attempts went
(counted from the boards), the procedure adopted after the foundation sprint
is measured over the two sprints since and kept, and the proposal prompt
lists what earlier procedures did. An Architect hired after the foundation
sprint briefs each new task after its first rework; the sprint list counts
the briefed tasks, and the Architect, asked again, is told how its earlier
brief went. Last, the help desk: the Support agent
(enabled for the run) triages a ticket from the public form beside the
reporter's choice, a support admin decides, `/v1/support/agent_record`
counts the decision, and the next ticket's prompt carries that record.
Then the Reviewer agent (enabled too): a run ingested from another
producer gets a suggested decision beside no approval, a Manager decides
against it, `/v1/agent_runs/reviewer_record` counts the miss beside what the
Verifier's verdict alone would have decided, and the next run's prompt
carries that record. Then a task whose file marks authentication is approved
by QA and still waits for a person (the risk tier, at autonomy level 3), the
inbox lists it as a high-risk hold, and a Manager accepts it.
At the end, `app/history_check.py` reads every task's history from the run's
database, sharing no code with the readers it checks, and the run fails on
an illegal one.
The fake model also checks the loop's order from its side: a QA review of a
task must follow a delivery of it, one review per delivery, and show QA the
files that delivery wrote; a violation fails the run.
Run it with the backend's interpreter (`E2E_PYTHON` pointing at the venv's
`python`, `$(cd backend && poetry env info --path)/bin/python`); it exits 0
only when every check passed and leaves the logs in `E2E_WORKDIR`. CI runs it
too (`.github/workflows/e2e.yml`) on every pull request that touches
`backend/`, `vscode-daemon/`, `scripts/e2e/` or the workflow itself, and on
pushes to `main`, against a `pgvector/pgvector:pg15` service and
a NATS container started with JetStream; the logs are kept as the `e2e-logs`
artifact.

`scripts/check_file_sizes.py` is a ratchet on file size: a source file
(backend app, daemon, proxy, scripts, the frontend's `src`, tests excluded)
stays at or under 600 lines, and the files already over it, listed with
their size in `scripts/file_size_baseline.json`, may shrink but never grow.
When one shrinks, `--update` lowers its entry. CI runs it on every pull
request that touches source (`.github/workflows/file-sizes.yml`).

The LLM proxy has its own suite under `llm-proxy/tests/` (model routing,
`unknown_model` 400s, upstream errors, catalogue-only fallback), run from the
repo root with the proxy's Poetry environment plus
`llm-proxy/requirements-dev.txt`: `python -m pytest llm-proxy/tests -q`. CI
runs it after the backend tests.

CI jobs run on GitHub-hosted runners (`runs-on: ubuntu-latest`). The
repository is public, so a self-hosted runner would run code from any fork's
pull request on that machine; keep every workflow on hosted runners. The e2e
still names its containers per run and lets Docker pick their ports, so it
is safe wherever it runs.

CI runs this suite on every pull request that touches `backend/` or the
workflow itself, and on pushes to `main`
(`.github/workflows/backend-tests.yml`), installing dependencies with Poetry
from `backend/poetry.lock`. The lint step runs the ruff version the workflow
pins (`pip install "ruff==0.17.1"`); lint locally with that same version, since
ruff's default rule set moves between releases. Feature-branch pushes do not trigger it; open a
pull request to get a run. Add new backend dependencies to
`backend/pyproject.toml` and commit the refreshed lock file; CI installs from
`backend/poetry.lock`.

Frontend changes are checked separately by
`.github/workflows/frontend-build.yml` on every pull request that touches
`frontend/` or the workflow itself, and on pushes to `main`.
That job runs `npm ci`, `npx tsc --noEmit`, `npm run lint`, `npm run test:run`,
and `npm run build` from the `frontend/` directory, using
`frontend/package-lock.json` as the cache key.
`frontend-build.yml` is the only frontend workflow: `frontend-tests.yml` was a
duplicate of the same checks on the same triggers and was removed.

`npm run lint` (`frontend/eslint.config.mjs`) enforces the i18n rule below with
`eslint-plugin-i18next`: any literal text in JSX, or in a `title`, `alt`,
`placeholder`, `aria-label` or `label` attribute, fails the build. Numbers,
punctuation, emoji, ALL_CAPS codes, hex colours, Tailwind class lists and the
brand name are allowed; keep value lists (enums, time zones) in module
constants rather than inline in JSX.

The frontend test suite uses Vitest with Testing Library and jsdom. Run it from
`frontend/` with `npm run test` for watch mode during development, or
`npm run test:run` for the non-watch CI/local verification command.

| File | What it covers |
|------|----------------|
| `src/components/AnalyticsDashboard.test.tsx` | Orchestration health KPI rendering, loading/error handling, empty state, and pre/post Batch 1 weekly trend behavior; how many Developer turns had no reported token count, shown only when some did |
| `src/pages/AgentSettings.test.tsx` | Model selector lists `/v1/models` entries after a "Default for role" option; a Viewer reads the agents with nothing to change them, a Manager changes them |
| `src/i18n/coverage.test.ts` | Every statically referenced translation key exists in both `en.json` and `es.json` |
| `src/App.test.tsx` | Navigation order, capability-gated links, redirects, language switcher |
| `src/pages/Sprints.test.tsx` / `src/hooks/useSprints.test.tsx` | Sprint list page and its `GET /v1/sprints` hook |
| `src/components/LearningTrend.test.tsx` | The "Is the company learning?" tiles: rework per task and blocked share per closed sprint, the change since the previous one, the sparkline's values and the table view; second attempts that got done, with and without the ScrumMaster's brief; tasks with console advice, and tasks the Architect briefed, against the rest |
| `src/pages/SprintWorkspace.test.tsx` | Sprint page tabs, URL sprint validation, Pause/Resume |
| `src/pages/TaskDetails.test.tsx` | Task page errors and delivery evidence |
| `src/pages/Procedures.test.tsx` | Proposals, procedures in force and history with their numbers; Manager adopt and write; load error retry |
| `src/components/Conversation.test.tsx` | Sprint and task conversation: who spoke to whom, kind filter, long messages, empty and error states |
| `src/components/GovernancePanel.test.tsx` | The Review inbox: blocked tasks with their reason and a Manager's "Send back to work", "Accept" on an approved high-risk delivery only, proposals linked to Procedures, undecided runs with the Reviewer agent's suggestion beside each and its record against the decisions, how earlier second attempts went beside the blocked tasks, Viewer and error states |
| `src/pages/EvidenceDetail.test.tsx` | Run page: claims beside observations, audit rows, the review form's validation and body, task links; the Reviewer agent's suggestion shown as a claim beside the review form, and when it could not suggest |
| `src/pages/HelpDesk.test.tsx` | Help desk for support admins: filters, resolution required to close, logs download, the agent's suggestions beside the reporter's choice, an admin's decision on impact and category (only a decision changed in the form is sent, one put back as the ticket stores it is not, an empty one clears it, one another admin made meanwhile is kept, a ticket another admin resolved meanwhile is not reopened, and after a save the form follows what is stored), the list showing the decided impact or the reporter's marked as theirs, the Support agent's record with its unusable answers and the reporters who chose |
| `src/viteConfig.test.ts` | Absolute asset base for the web build (deep links), relative only for Electron |
| `src/store/agentStore.test.ts` | The Glassroom connection asks for a stream ticket on every connection, opens without one when none is needed or none could be had, and opens nothing once disconnected; an event the backend replays on a reconnection is shown once |

### Manual validation (no test deps needed)

```bash
# Health check
curl http://localhost:8000/health

# Manual API test
curl -X POST http://localhost:8000/v1/init_company \
  -H "Content-Type: application/json" \
  -d '{"company_name": "Test Corp"}'

# Full API reference
open http://localhost:8000/docs
```

## Frontend i18n

All user-facing strings must be added to both:
- `frontend/src/i18n/en.json`
- `frontend/src/i18n/es.json`

Use the `useTranslation` hook from i18next; never hardcode English strings in JSX.

## LLM Proxy Model Routing

Every LLM call goes through the proxy client (`backend/app/llm_proxy_client.py`).
`LLMProxyClient.chat()` / `chat_async()` take a `model` id (default
`"gemini-pro"`), a `role`, and an optional `bu_id`. There is no
`model_preference` parameter: the `fast` / `powerful` tiers are an internal
fallback in the proxy (`_PREFERENCE_TIERS`). Role→model defaults live in
`backend/llm/model_factory.py` (`ModelFactory.ROLE_MODEL_MAP`).

Token budgets are enforced per company at the proxy layer — the backend never calls a model provider directly.

## Documentation

- [`README.md`](README.md) — Project overview, architecture, setup, and API reference
- Branches: trunk-based. Each change is a branch cut from `main` with one pull request into `main`, merged once the head is green (`CONTRIBUTING.md`, Branches). There is no `develop` integration branch.
- The Glassroom VR entry for the Meta VR Start Developer Competition lives on
  the `main_meta` branch (`vr/`, `docs/VR_ENTRY.md`); `main` is the web product.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Development standards and workflows
- [`SECURITY.md`](SECURITY.md) — Security policy and vulnerability reporting
- [`docs/POSITIONING.md`](docs/POSITIONING.md) — Project direction and design rules
