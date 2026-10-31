# La Fabrique — hackathon entry

**Nebius × NVIDIA Global AI Hackathon.** Public repository, Apache 2.0.
Delivery deadline: **30 October 2026, 14:00 GMT-3**.

- Repository: <https://github.com/careb36/la-fabrique>
- License: Apache 2.0 — see [LICENSE](../LICENSE)
- Commits are written in Spanish (the team's convention)

## The pitch

AI agents are cheap and abundant. What is scarce is a **trustworthy answer to
one question** about the work they produce:

> Did this agent actually do what it says it did?

La Fabrique is an AI software factory whose product is not the agents — the
agents are interchangeable. The product is the **verification and evidence
layer** that sits around them. It ingests an agent's work, checks it
deterministically against what is on disk and what CI reports, and stores the
result as evidence, kept strictly separate from the agent's own claims.

Three verdicts, not two: `verified`, `refuted`, and `unverifiable`. A model may
summarise a refutation for a person afterwards; it never decides whether a
claim holds.

## What runs it

| Layer | Technology |
| --- | --- |
| Control plane | FastAPI + SQLModel, PostgreSQL with pgvector |
| Evidence & lineage | Deterministic verifier, append-only signed audit chain, Neo4j engram graph |
| Async path | Transactional outbox → NATS JetStream → task worker → workspace daemon |
| Model access | A single LLM proxy that enforces per-company token budgets and routes by model id |
| Frontend | React 18 + TypeScript + Tailwind, over REST and Server-Sent Events |

## Nebius × NVIDIA: where Nemotron enters

Every model call goes through `llm-proxy/`, and the proxy routes NVIDIA open
models to **Nebius Token Factory** over its OpenAI-compatible endpoint. The
model catalogue is fetched live at startup and hourly, so new Nemotron releases
appear without a code change:

| Route | Setting | Example model |
| --- | --- | --- |
| strategic | `NEMOTRON_MODEL_STRATEGIC` | `nvidia/nemotron-3-ultra-550b-a55b` |
| default | `NEMOTRON_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| fast | `NEMOTRON_MODEL_FAST` | `nvidia/nemotron-3-super-120b-a12b` (a Nano id once your catalogue lists one) |

`NEMOTRON_ROLES` says which agent roles run on Nemotron. The shipped
`.env.example` opts **every role** in, so a stack started from it with a
`NEBIUS_API_KEY` runs PO, Architect and SecOps on Nemotron 3 Ultra and every other role on
Nemotron 3 Super (point `NEMOTRON_MODEL_FAST` at a Nano id to move the
TechWriter); clearing the
variable falls back to the Qwen/DeepSeek defaults. `scripts/verify-nebius.sh`
proves the three layers separately so a failure points at the broken one. See
[Model Providers](../README.md#model-providers-nebius--nvidia-nemotron).

### Running a sprint on Nemotron

```bash
cp .env.example .env            # Nemotron is already on for every role
# set NEBIUS_API_KEY, POSTGRES_PASSWORD, NEO4J_PASSWORD, JWT_SECRET_KEY in .env
docker compose up -d
NEBIUS_API_KEY=... PROXY_URL=http://localhost:5100 ./scripts/verify-nebius.sh
curl -s http://localhost:5100/v1/models | jq '.models[] | select(.provider=="nebius") | .id'
```

Then start the workspace daemon (`scripts/start-daemon.sh`), create a company
and a sprint from the frontend, and open the sprint's Glassroom: each agent
turn names the model that served it (`served_model` on the run, the model id in
the audit rows), so a Nemotron sprint is distinguishable from any other.

## Hosted demo

There is no public deployment: the workspace daemon writes to the folder of the
person running it, so a shared instance would write to nobody's project. The
stack runs on any Linux machine with Docker in the three commands above
(frontend on `:5173`, API and Swagger on `:8000/docs`, proxy on `:5100`); set
`PUBLIC_API_URL` to the machine's public address if GitHub webhooks should
reach it. The demo video walks through a stack filled by the end-to-end run
(`scripts/e2e/run.sh`, the same run CI executes on every pull request).

## The 5-minute demo (no API keys)

The whole point of the product is that the three verdicts exist and are
distinguishable — so the demo seeds one run per verdict and shows the screen
that tells them apart. No model or collector key is needed.

1. Start the stack and register a user (see [README](../README.md#installation)).
2. Seed the evidence layer:

   ```bash
   python3 scripts/seed_demo_evidence.py --company-id 1
   ```

3. Open `/evidence`. Three runs, one per verdict: **verified**, **refuted**,
   **unverifiable**. Open each to see the claim on one side and the independent
   observations on the other.

The seed is idempotent: each run carries a fixed `external_ref`, and a run that
already has a verification is left alone. The screenshots in the
[README](../README.md#screenshots) are this exact demo.

## Evidence that it works

Run against a clean checkout; each command was run to completion and is quoted
with its real result, not estimated.

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `cd backend && PYTHONPATH=.:app python3 -m pytest tests -q` | 771 passed |
| Backend lint | `cd backend && ruff check app tests && ruff format --check app tests` | clean |
| Frontend tests | `cd frontend && npm run test:run` | 392 passed (49 files) |
| Frontend typecheck | `cd frontend && npx tsc --noEmit` | clean |
| Frontend lint | `cd frontend && npm run lint` | clean |
| Frontend build | `cd frontend && npm run build` | built |
| LLM proxy tests | `cd llm-proxy && poetry run python -m pytest tests -q` | 24 passed |

Continuous integration runs on every pull request (path-filtered backend,
frontend, proxy, e2e, security and file-size jobs) on GitHub-hosted runners.

## Built during the hackathon

The repository predates the hackathon; this is what was added for it (details
in the [CHANGELOG](../CHANGELOG.md)):

- **Nebius Token Factory as a model provider** in the LLM proxy: prefix
  routing for `nvidia/` and the other vendor ids, the catalogue fetched live
  at startup and hourly, `GET /v1/models` listing what it found, and each
  answer saying whether its token count was reported by the provider or
  estimated.
- **Per-role Nemotron opt-in** (`NEMOTRON_ROLES`, `NEMOTRON_MODEL`,
  `_STRATEGIC`, `_FAST`), on for every role in the shipped `.env.example`,
  and `scripts/verify-nebius.sh` to prove the key, the catalogue and a
  completion separately.
- **The Architect consultation step** and the orchestration KPIs that read
  real data (Developer tokens per turn, QA rework rate, Architect consult
  frequency).
- **Public-repository hygiene**: CI on GitHub-hosted runners, no personal data
  in the tree, an error handler that only claims a report it sent.
- **Documentation**: this page, the README's model-provider and Nebius
  sections, the evidence-page screenshots and the responsible-use notes.

## What the judges should look at

- **The evidence layer, not the agents.** `backend/app/services/verification.py`
  is where claims and observations are kept apart and `unverifiable` is a first-class
  verdict.
- **The audit chain.** `POST /v1/audit` signs entries; `GET /v1/audit/chain`
  walks the chain and reports where it breaks.
- **The Nebius/NVIDIA wiring.** `llm-proxy/` fetches the Token Factory catalogue
  live and routes Nemotron ids; nothing about Nebius is hardcoded.
- **The governance story.** A blocked task is triaged by the ScrumMaster in a
  fixed, parsable format, and the Review page shows a person what needs them.
