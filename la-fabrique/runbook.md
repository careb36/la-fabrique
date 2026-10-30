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

La Fabrique ships with OpenTelemetry instrumentation across the backend, LLM proxy, and agent worker.
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
- `fabrique-api` — FastAPI request traces
- `agent-worker` — LangGraph node spans (`graph.po`, `graph.architect`, …)
- `llm-proxy` — LLM API call traces with quota context

---

## 1. Secrets Management

### Current State (Development)
- API tokens stored in environment variables
- Database passwords in `.env`

### Production Steps

#### HashiCorp Vault Integration
```python
# Replace environment variable access with Vault
import hvac

client = hvac.Client(url='https://vault.example.com', token='...')

# Read secrets
gemini_api_key = client.secrets.kv.v2.read_secret(
    path='le-fabrique/llm'
)['data']['data']['gemini_api_key']

deepseek_api_key = client.secrets.kv.v2.read_secret(
    path='le-fabrique/llm'
)['data']['data']['deepseek_api_key']
```

#### AWS KMS (Alternative)
```python
import boto3

kms = boto3.client('kms')
response = kms.decrypt(CiphertextBlob=base64.b64decode(encrypted_token))
token = response['Plaintext'].decode()
```

## 2. Network Security

### mTLS Configuration for NATS

```yaml
# docker-compose.override.yml
services:
  nats:
    command: "--tlsverify --tlscert=/certs/server.crt --tlskey=/certs/server.key"
    volumes:
      - ./certs:/certs:ro
  
  backend:
    environment:
      NATS_URL: nats://nats:4222
    volumes:
      - ./certs:/certs:ro
```

## 3. Token Budget Enforcement

### LLM Proxy Routing
*Note: All models (including DeepSeek for Devs/QA) MUST route through the local `llm-proxy` (`http://localhost:5100`) to ensure global token budgets are respected and keys are centralized.*

### LLM Proxy Token Budget

```python
# llm-proxy/app.py (add budget tracking)
from collections import defaultdict

token_budgets = defaultdict(lambda: {"used": 0, "limit": 2_000_000})

@app.middleware("http")
async def enforce_token_budget(request, call_next):
    agent_id = request.headers.get("X-Agent-ID")
    if agent_id:
        if token_budgets[agent_id]["used"] >= token_budgets[agent_id]["limit"]:
            return JSONResponse(
                status_code=429,
                content={"error": "Token budget exceeded"}
            )
    
    response = await call_next(request)
    
    # Track usage
    tokens_used = int(response.headers.get("X-Tokens-Used", 0))
    token_budgets[agent_id]["used"] += tokens_used
    
    return response
```

## 4. Agent Commit Verification

### Git Hook for Verification
```bash
# .git/hooks/pre-receive
#!/bin/bash
while read oldrev newrev refname; do
    commit_msg=$(git log -1 --format=%B $newrev)
    interaction_id=$(echo "$commit_msg" | grep -oP 'interaction_id: \K.*')
    decision_sig=$(echo "$commit_msg" | grep -oP 'decision_signature: \K.*')
    
    if [ -z "$interaction_id" ] || [ -z "$decision_sig" ]; then
        echo "Commit must include interaction_id and decision_signature"
        exit 1
    fi
done
```

## 5. Distributed Transactions (Outbox Pattern)
The system uses the Transactional Outbox pattern (`outbox_events` table in Postgres) to guarantee NATS message delivery, preventing sync issues between Postgres and LangGraph.

- **Background Worker**: The `process_outbox` task in `backend/app/main.py` polls this table and safely dispatches events.
- **Monitoring**: Ensure you monitor the `outbox_events` table for records stuck in `failed` or perpetually in `pending` status, which indicates NATS connectivity issues.

## 6. Scaling Considerations

### Horizontal Scaling
- Backend: Deploy multiple replicas with load balancer
- NATS: Use NATS cluster for high availability
- Postgres: Use read replicas for query scaling

### Resource Recommendations
| Service | CPU | Memory | Storage |
|---------|-----|--------|---------|
| backend | 2 cores | 4 GB | - |
| postgres | 4 cores | 8 GB | 100 GB |
| neo4j | 4 cores | 8 GB | 50 GB |
| nats | 1 core | 512 MB | - |

## 7. Backup Strategy

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

## 8. Hybrid Deployment Architecture

Fabrique is designed to run anywhere. Choose the strategy that fits your security and scaling needs:

### 🏠 Strategy A: On-Premise (Private Servers)
Best for maximum data privacy and strict compliance environments.
*   **Infrastructure:** Physical servers, VM clusters (VMWare/Nutannix).
*   **Orchestration:** Docker Compose for single-server or Kubernetes (OpenShift/Rancher) for clusters.
*   **Storage:** Local persistent volumes (HostPath or local-static-provisioner).
*   **AI Access:** Requires an outbound proxy/firewall rule to reach Gemini/DeepSeek APIs.

### ☁️ Strategy B: Cloud-Native (AWS, Azure, GCP)
Best for high availability, global reach, and zero infrastructure maintenance.
*   **Infrastructure:** Managed Kubernetes (EKS/AKS/GKE).
*   **Database:** Use high-availability managed services (AWS RDS, Google Cloud SQL).
*   **Secrets:** Native integration with Cloud KMS and Secrets Managers.
*   **Scaling:** Vertical and horizontal auto-scaling based on CPU/Memory/Task Queue depth.

### 🌉 Strategy C: Hybrid Model
Data and Logic remain On-Premise (for security), while heavy computation (LLMs) happens in the Cloud via the secure `llm-proxy`.

---

## 9. Kubernetes Quick Start
To deploy the Enterprise cluster:
```bash
kubectl apply -f deployment/k8s/configmap.yaml
kubectl apply -f deployment/k8s/secrets.yaml
kubectl apply -f deployment/k8s/backend.yaml
---

## 10. Proactive Support & Telemetry (Vendor Flow)

Fabrique includes an Enterprise-grade telemetry system that can report core engine failures to a support webhook (`FABRIQUE_VENDOR_SUPPORT_URL`, opt-in) without exposing sensitive client data or source code.

### The Secure Telemetry Flow:
1. **Error Detection:** If a critical backend error occurs (HTTP 500), the Global Exception Handler intercepts the crash.
2. **Data Sanitization:** The system extracts *only* the technical stack trace, endpoint, and Fabrique version. **No client data, prompts, or proprietary code is ever transmitted.**
3. **Vendor Webhook:** The sanitized report is sent via secure HTTPS POST to the `FABRIQUE_VENDOR_SUPPORT_URL`.
4. **Centralized Resolution:** The vendor's infrastructure receives the report, aggregates duplicate issues, and automatically creates an engineering ticket in the core GitHub repository.
5. **Patch Delivery:** The vendor releases a system update (Docker image) to resolve the issue for all clients globally.

*Note for IT Admins: This outbound connection is read-only from the client's perspective and requires port 443 (HTTPS) access to the vendor's telemetry endpoint.*

## 11. Security Checklist

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

For issues or questions, refer to the project documentation or contact the platform team.
