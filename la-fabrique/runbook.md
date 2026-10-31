# Production Hardening Runbook

This document describes steps to harden the Factory system for production deployment.

## Service URLs

| Service | URL | Description |
|---|---|---|
| Frontend | `http://localhost:5173` | React dashboard |
| Backend API | `http://localhost:8000/docs` | FastAPI + Swagger |
| LLM Proxy | `http://localhost:5100` | Token budget gateway |
| **Jaeger Tracing UI** | **`http://localhost:16686`** | Distributed trace explorer |
| Neo4j Browser | `http://localhost:7474` | Knowledge graph UI |

---

## Distributed Tracing (OpenTelemetry + Jaeger)

La Fabrique ships with OpenTelemetry instrumentation in the LLM proxy and the LangGraph agent graph.
Traces flow to the Jaeger all-in-one container via OTLP/HTTP on port `4318`.

**Enabling traces** (default in Docker Compose):
```
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
```

**Disabling traces** (e.g. to reduce overhead):
```
OTEL_SDK_DISABLED=true
```

**Key service names in Jaeger:**
- `agent-worker` — LangGraph node spans (`graph.po`, `graph.architect`, …), set up by `backend/agents/graph.py` inside the backend process
- `llm-proxy` — the proxy's Flask request spans and its outgoing provider calls

The backend's FastAPI routes are not instrumented; their request counts and latencies are on `/metrics` (Prometheus).

---

## 1. Secrets Management

### Current State (Development)
- API tokens stored in environment variables
- Database passwords in `.env`

### Production Steps

The backend and the LLM proxy read their secrets only from environment
variables. In production, have your secret manager (Vault, a cloud KMS, or
Kubernetes Secrets) inject them into the containers' environment, and set the
optional keys too:

- `JWT_SECRET_KEY` — required for login.
- `FERNET_SECRET_KEY` — encrypts stored project credentials.
- `AUDIT_SIGNING_KEY` — signs audit rows and keys each company's audit hash chain.
- `VOICE_API_KEY` — only if the desktop assistant drives the factory.

Provider keys (`NEBIUS_API_KEY`, `NVIDIA_API_KEY`, `GEMINI_API_KEY`,
`DEEPSEEK_API_KEY`, `QWEN_API_KEY`) go to the `llm-proxy` container only.

## 2. Network Security

### Published ports

Every port `docker-compose.yml` publishes binds to `BIND_ADDRESS`, and NATS to
`NATS_BIND`; both default to `127.0.0.1`. The shipped NATS has no
authentication or TLS, and anything that reaches it can ask the workspace daemon
to run commands, so keep `NATS_BIND` on loopback unless the network is one you
control. Set `BIND_ADDRESS=0.0.0.0` only behind a firewall.

## 3. Token Budget Enforcement

### LLM Proxy Routing
*Note: All models (including DeepSeek for Devs/QA) MUST route through the local `llm-proxy` (`http://localhost:5100`) to ensure per-business-unit token budgets are respected and keys are centralized.*

### LLM Proxy Token Budget

Budgets are per business unit, stored in the `business_units` table
(`token_quota_limit`, `token_quota_used`). Before each request that carries an
`X-Business-Unit-ID` header, `llm-proxy/app.py` answers 429 when a unit with a
non-zero limit has used it up, adds `X-Quota-Warning` once 80 % is spent, and
adds each answer's tokens to `token_quota_used`. Viewers read the budgets at
`GET /v1/enterprise/quotas`; a Manager resets one with
`POST /v1/enterprise/quotas/{bu_id}/reset`.

## 4. Distributed Transactions (Outbox Pattern)
The system uses the Transactional Outbox pattern (`outbox_events` table in Postgres) to guarantee NATS message delivery, preventing sync issues between Postgres and NATS.

- **Background Worker**: `process_outbox` (`backend/app/services/outbox_service.py`), started by `backend/app/lifecycle.py` once NATS connects, polls this table and dispatches events. A row is marked `completed` once stored, and `failed` after five unsuccessful attempts.
- **Monitoring**: Ensure you monitor the `outbox_events` table for records stuck in `failed` or perpetually in `pending` status, which indicates NATS connectivity issues.

## 5. Scaling Considerations

### Horizontal Scaling
- Backend: some state lives in the process — the Glassroom SSE fan-out, the desktop handoff codes and the rate-limit counters (`RATE_LIMIT_STORAGE_URI=memory://`) — so a second replica does not share it.
- NATS: Use NATS cluster for high availability

### Resource Recommendations
| Service | CPU | Memory | Storage |
|---------|-----|--------|---------|
| backend | 2 cores | 4 GB | - |
| postgres | 4 cores | 8 GB | 100 GB |
| neo4j | 4 cores | 8 GB | 50 GB |
| nats | 1 core | 512 MB | - |

## 6. Backup Strategy

### Postgres
```bash
# Backup script
pg_dump -h postgres -U factory factory > backup_$(date +%Y%m%d).sql
```

### Neo4j
```bash
# Backup using neo4j-admin
docker exec factory-neo4j neo4j-admin database dump neo4j --to-path=/backup
```

## 7. Hybrid Deployment Architecture

The stack is a set of containers plus the workspace daemon on the machine that holds the projects. These are the usual ways to place them:

### 🏠 Strategy A: On-Premise (Private Servers)
Best for maximum data privacy and strict compliance environments.
*   **Infrastructure:** Physical servers, VM clusters (VMWare/Nutannix).
*   **Orchestration:** Docker Compose for single-server or Kubernetes (OpenShift/Rancher) for clusters.
*   **Storage:** Local persistent volumes (HostPath or local-static-provisioner).
*   **AI Access:** Requires an outbound proxy/firewall rule from `llm-proxy` to the model providers you use (Nebius Token Factory, NVIDIA, Gemini, DeepSeek, Qwen).

### ☁️ Strategy B: Cloud-Native (AWS, Azure, GCP)
Best for high availability, global reach, and zero infrastructure maintenance.
*   **Infrastructure:** Managed Kubernetes (EKS/AKS/GKE).
*   **Database:** Use high-availability managed services (AWS RDS, Google Cloud SQL).
*   **Secrets:** Inject them from the cloud's secret manager as environment variables.

### 🌉 Strategy C: Hybrid Model
Data and Logic remain On-Premise (for security), while heavy computation (LLMs) happens in the Cloud via the secure `llm-proxy`.

---

## 8. Kubernetes Quick Start
`deployment/k8s/backend.yaml` is the only manifest: a three-replica backend
Deployment (image `fabrique-backend:latest`) and a `LoadBalancer` Service on
port 80. It reads its environment from a Secret named `fabrique-secrets` and a
ConfigMap named `fabrique-config`, which you create first:
```bash
kubectl create secret generic fabrique-secrets --from-env-file=.env
kubectl create configmap fabrique-config --from-literal=AUTH_REQUIRED=true
kubectl apply -f deployment/k8s/backend.yaml
```
Postgres, NATS, Neo4j and the LLM proxy are not in the manifest. Read the
scaling note above before keeping three replicas.

---

## 9. Error Reports (Support Webhook)

An unhandled backend error (HTTP 500) is handled by the global exception
handler in `backend/app/exception_handlers.py`:

1. **Logging:** the error and the last 1,000 characters of its traceback are logged.
2. **Support webhook (opt-in):** only when `FABRIQUE_VENDOR_SUPPORT_URL` is set, a JSON report is POSTed to it with the installation id (`FABRIQUE_VENDOR_ID`), the version, the error type and message, that traceback excerpt and the endpoint. An error message or traceback can include data from the request, so point it only at an endpoint you trust.
3. **Ticket event:** a `system.maintenance.create_ticket` event is published on NATS.

The response says whether the report reached the webhook.

## 10. Security Checklist

- [ ] Rotate all default passwords
- [ ] Enable NATS authentication
- [ ] Enable Postgres SSL connections
- [ ] Enable Neo4j SSL connections
- [ ] Configure firewall rules
- [ ] Set up Vault for secrets
- [ ] Enable audit logging
- [ ] Configure rate limiting
- [ ] Set up WAF (Web Application Firewall)
- [ ] Regular security updates

## Contact

For issues or questions, refer to the project documentation or open an issue in the repository. Report security problems privately, as `SECURITY.md` describes.
