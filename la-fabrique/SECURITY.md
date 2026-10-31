# SECURITY.md — La Fabrique Multi-Agent Platform

**Version:** 1.0
**Owner:** Security Engineering
**Applies to:** FastAPI control plane, React/Vite frontend, LangGraph agents, PostgreSQL, Neo4j, Kubernetes deployments
**Last reviewed:** Sprint 0 — Foundations

---

## 1. Purpose and Scope

This document defines the security requirements, secure coding rules, and review process for the La Fabrique multi-agent orchestration platform. It is binding for all agents, services, and pull requests that touch:

- FastAPI APIs and middleware
- React/Vite frontend and static asset delivery
- LangGraph agent graphs, prompts, and tool definitions
- PostgreSQL and Neo4j persistence layers
- Kubernetes manifests, Helm charts, container images, and CI/CD pipelines

The goal is to ensure the platform is secure by default, auditable, and resilient against both classic web/API attacks and LLM-specific risks such as prompt injection and tool-call abuse.

---

## 2. Threat Model Overview

Primary trust boundaries:

1. **End user ↔ Frontend** — browser-based attacks, token theft, XSS, CSRF, supply chain.
2. **Frontend ↔ FastAPI** — authentication, authorization, injection, rate limiting, TLS.
3. **FastAPI ↔ LangGraph Agents** — prompt injection, unsafe tool selection, data exfiltration.
4. **Agents ↔ External Tools/APIs** — tool-call abuse, excessive permissions, secret leakage.
5. **Services ↔ PostgreSQL/Neo4j** — database compromise, unauthorized queries, data leakage.
6. **CI/CD ↔ Kubernetes/Registry** — malicious images, leaked secrets, supply chain compromise.

Key threat actors: malicious end users, compromised external content, malicious model output, insider developers, CI/CD attackers.

Reference frameworks:
- OWASP Top 10 for LLM Applications
- OWASP ASVS 4.0
- OWASP Kubernetes Top 10
- NIST 800-218 SSDF

---

## 3. Authentication and Authorization

### 3.1 Identity Provider

- Use **OIDC/OAuth 2.1** with a trusted IdP for all human users.
- Frontend uses **Authorization Code with PKCE** for SPAs. Never use implicit flow.
- Backend validates JWT access tokens on every request. Accept only tokens signed by the configured IdP and with correct `iss`, `aud`, `exp`, `nbf`.
- Short-lived access tokens: **≤ 15 minutes**.
- Refresh tokens are server-side, rotated on use, and bound to the client.

### 3.2 API Authorization

- Enforce **RBAC/ReBAC** at the FastAPI layer.
- Define roles: `admin`, `operator`, `agent-developer`, `viewer`.
- Use a **deny-by-default** policy: no endpoint is public unless explicitly declared.
- Route-level authorization must be enforced by middleware or dependencies, not only in UI.
- Each LangGraph agent run must inherit the caller’s identity and permissions. Never let an agent perform actions the calling user cannot perform.
- Service-to-service calls use **mTLS** or a hardened service mesh identity. Do not share user tokens between services.

### 3.3 Frontend Exposure

- Protect all frontend routes with authentication guards; that is UX only, not security.
- Store tokens in **memory only** or secure, `HttpOnly`, `SameSite=Lax/Strict` cookies. Never in `localStorage` or `sessionStorage`.
- Configure Vite and ingress with:
  - `Content-Security-Policy` without `unsafe-inline` for scripts
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `Permissions-Policy` limited to required features
  - `Cross-Origin-Opener-Policy: same-origin`
- CORS: allow only known frontend origins. Never use `*` with credentials.
- Build-time environment variables must **not** contain secrets. They are embedded in the bundle.

---

## 4. Secret Handling

### 4.1 Rules

- **No secrets in source code, Dockerfiles, Helm values, or frontend bundles.**
- Use an external secret manager: HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, or Kubernetes External Secrets Operator.
- Kubernetes Secrets must be encrypted at rest and mounted as files or environment variables only where needed. Prefer CSI drivers over plain `env`.
- Never log secrets, tokens, API keys, or full request/response payloads.
- Apply least privilege to service accounts and API keys.
- Rotate credentials automatically. Maximum lifetime for static credentials: **90 days**.
- Prefer workload identity / IRSA / Workload Identity Federation over static cloud keys.

### 4.2 Development

- `.env` files are ignored by git and must never be committed.
- Use a pre-commit hook and CI check for secrets: `gitleaks`, `trufflehog`, or `detect-secrets`.
- Example placeholders: `${DB_PASSWORD}` from secret manager. No default fallback in production.

### 4.3 Detection

- CI scans all PRs for secrets and high-entropy strings.
- Alerts on secret exposure trigger the incident response process.

---

## 5. Dependency and Supply Chain Security

### 5.1 Lockfiles and Pinning

- Use exact pinned dependencies:
  - Python: `requirements.txt` hashes or `poetry.lock`
  - Node: `package-lock.json` with `npm ci`
- Commit lockfiles to the repository.
- Do not use `latest` or floating tags in production image builds.

### 5.2 Scanning

- CI must run on every PR:
  - `pip-audit` or `pipenv check` for Python
  - `npm audit --omit=dev` for Node
  - `trivy fs` or `grype` for OS and language packages
- Container images scanned with `trivy image` or `grype` before push and before deploy.
- Generate an **SBOM** for each production image (CycloneDX/SPDX).
- Dependency update automation: Renovate or Dependabot enabled with security updates.

### 5.3 Supply Chain

- Use signed commits and signed tags.
- Container images signed with `cosign`; verify signature in admission control.
- Build from pinned, minimal base images. Do not pull `latest` base images.
- Restrict CI/CD pipeline permissions. Approval required for changes to `.github/workflows` or deploy files.

### 5.4 Advisories

`npm audit --omit=dev`, the surface a browser actually receives, reports no
known vulnerabilities. React Router 7, Vite 8, Vitest 5 and Electron 45 are
the versions in use.

Build and lint tooling carries one moderate advisory, GHSA-g3hv-75wg-m249
(`minimatch`, denial of service through crafted glob patterns), reached only
through `eslint`, `typescript-eslint` and `electron-builder`. Those run on a
developer's or CI machine against the repository's own patterns; none of them
is in the `dist/` bundle the frontend ships.

`pip-audit` over `backend/poetry.lock` and the LLM proxy's lock reports nothing.
Each `ignore` in `.github/dependabot.yml` carries its reason next to it.

---

## 6. Container and Kubernetes Hardening

### 6.1 Container Images

- Use **distroless** or minimal Alpine images. No shells, compilers, or debug tools in production.
- Run as **non-root** user with a fixed UID, ideally > 10000.
- Set `readOnlyRootFilesystem: true` except for volumes.
- Drop all Linux capabilities; add only explicitly required ones.
- Define `resources.requests` and `resources.limits`.
- Avoid mounting `docker.sock` or host paths.

### 6.2 Kubernetes Deployments

- Enable Pod Security Standards: `restricted` for app namespaces.
- Network policies: default deny, then allow only required ingress/egress:
  - Frontend → API
  - API → PostgreSQL/Neo4j
  - API → agent tool endpoints
- Use encrypted storage classes for PostgreSQL/Neo4j volumes.
- Enable Kubernetes audit logging; ship to SIEM.
- Disable auto-mount of service account tokens unless needed.
- Lock down RBAC: each workload gets its own ServiceAccount with minimal permissions.
- Admission policies: block privileged pods, host networking, unknown registries.

---

## 7. Data Privacy and Database Security

### 7.1 PostgreSQL and Neo4j

- Use **least privilege database users**. The API must not use superuser accounts.
- Separate schemas/databases per service or tenant where applicable.
- Enforce TLS between services and databases. Never connect with plaintext credentials.
- Enable audit logging for database connections and privileged operations.

### 7.2 Data Handling

- Data minimization: store only what is required for the product.
- Classify data: public, internal, confidential, regulated.
- For **PII/sensitive fields**, use application-level encryption (e.g., `pgcrypto`, envelope encryption) or rely on disk encryption plus strict access controls.
- Anonymize/pseudonymize in non-production environments.
- Define retention policy: delete or archive data when no longer needed.
- Honor GDPR/CCPA deletion and export requests. Build data subject request APIs with audit trail.
- Do not include sensitive data in logs, traces, or error messages.
- Backups must be encrypted and access-restricted. Test restore procedures.

### 7.3 Neo4j-Specific

- Disable Neo4j Browser in production if not required.
- Use built-in role-based access control; avoid `neo4j` admin for application connections.
- Constrain Cypher queries. Use parameterized queries and avoid string concatenation.
- For graph data containing relationships between entities, consider row-level security via custom procedures or separate databases per tenant.

---

## 8. LLM and Agent Security

### 8.1 Prompt Injection

Treat **all external content** as potentially malicious. This includes documents, web pages, emails, and output from other agents.

Core rules:

- **Model output is untrusted.** Never execute or evaluate model output as code, SQL, Cypher, or shell commands directly.
- Separate **instructions from data**. Use delimiters and make clear that content inside data sections is not instructions.
- Do not let agents fetch arbitrary URLs unless the target is on an allowlist and responses are treated as untrusted.
- Use a **system prompt** that explicitly forbids following instructions embedded in user data.
- Implement guardrails: input filtering for known injection patterns, output filtering for forbidden content, and a second LLM classifier for sensitive actions if risk demands.
- For high-impact actions, require **human approval** before execution.

### 8.2 Tool-Call Abuse

- **Tool allowlist per agent.** An agent can only call tools explicitly assigned to its role.
- Each tool call must be validated:
  - Input schema validation (types, lengths, enums, constraints)
  - Authentication context check: does the calling agent/user have permission?
  - Rate limiting per tool, per agent, per user
  - Timeouts and maximum result sizes
- Do not give agent tools broad powers. Prefer **narrow, scoped tools**:
  - `read_only` instead of `write`
  - one resource instead of `*`
- Use **scoped credentials** for each tool. Never share the agent’s main identity with third-party APIs.
- Log every tool call: agent ID, user ID, tool name, input signature/hash, timestamp, result status. This is critical for audit and abuse detection.
- For tools that modify state, require idempotency keys and maintain an audit trail.
- Never expose raw database connection or Kubernetes API as a tool.

### 8.3 Workspace Command Execution

`vscode-daemon/daemon.py` runs workspace commands through the host shell, with
the privileges of the person who started it. It is not a sandbox, and it keeps
no command blocklist: a blocklist screens a string and cannot fence a process
(`rm -rf`, `rm -r -f` and `rm --recursive --force` are one intent spelled three
ways).

- The daemon is **host-side, by design** (`./scripts/start-daemon.sh`, not in
  Docker), so a workspace command runs as the developer who started it.
- The commands the pipeline runs on its own are **not** model output:
  `_detect_test_command` in `backend/app/services/task_worker.py` derives the
  test command from repository markers (`package.json`, `pytest.ini`,
  `pyproject.toml`, a `tests/` folder) or from `DELIVERY_TEST_COMMAND`. No LLM
  picks it, so prompt injection cannot reach that string.
- The daemon listens on NATS with a scoped namespace, the subjects it accepts
  are a fixed list, and NATS binds to `127.0.0.1` by default (`NATS_BIND`).

Treat `workspace.execute` as privileged: connect the daemon only to brokers you
trust, and do not point it at a workspace whose commands you would not run
yourself.

### 8.4 LangGraph-Specific

- Validate all **state** passed between nodes. Do not assume earlier nodes sanitized data.
- Keep agent graphs deterministic where possible; constrain branching based on fixed logic, not LLM output, for security-critical branches.
- Use structured output parsing for security decisions. Never rely on free-text model response to determine authorization.
- Restrict LangGraph tool nodes to a pre-registered set. Implement a registry of allowed tools with permissions.

### 8.5 Model Output Handling

- **Encode output** before rendering in frontend to prevent XSS.
- Sanitize any model output inserted into SQL, Cypher, JSON, HTML, or logs.
- Limit output size to avoid DoS.
- Do not render markdown/HTML from untrusted model output without a sanitizer.

---

## 9. Incident Response

### 9.1 Reporting

- Report security incidents to `security@your-org.example` immediately.
- Do **not** open a public issue for suspected vulnerabilities.
- Include affected component, timestamp, impact, and any reproduce steps.

### 9.2 Severity Levels

| Severity | Examples | Response Time |
|---|---|---|
| Critical | Unauthorized admin access, remote code execution, prompt injection leading to tool abuse, secret exposure | 24h containment |
| High | Data exfiltration, auth bypass, XSS on auth pages | 72h |
| Medium | Missing security headers, excessive logging, misconfiguration | 1 week |
| Low | Best practice deviations, low-impact issues | Next sprint |

### 9.3 Process

1. **Preparation:** maintain contact list, runbooks, backup restore procedures.
2. **Detection and analysis:** SIEM alerts, audit logs, tool-call anomaly detection.
3. **Containment:** revoke compromised tokens/keys, isolate affected services, disable tool or agent.
4. **Eradication:** remove injected data, patch root cause, rotate secrets.
5. **Recovery:** restore from clean backups, re-enable services with increased monitoring.
6. **Post-incident:** blameless retro, update SECURITY.md, add regression tests.

### 9.4 Immediate Actions for LLM Incidents

- Suspend the affected agent/tool.
- Freeze any agent state and logs for forensics.
- Revoke tool credentials and rotate them.
- Determine if prompt injection came from external data or user input.
- Assess whether model output was rendered unsafely or executed.

---

## 10. Security Review Checklist for Agents and PRs

Every PR that touches backend, frontend, agents, or infrastructure must pass this checklist before merge.

### 10.1 General

- [ ] No secrets or credentials in code, config, or comments
- [ ] Dependencies pinned and lockfiles updated
- [ ] Dependency and container scans pass
- [ ] No secret patterns in logs
- [ ] Error messages do not leak stack traces or internal details

### 10.2 Authentication and Authorization

- [ ] New endpoints enforce authentication unless explicitly public and approved
- [ ] Authorization checked server-side for every role/permission
- [ ] Token validation includes signature, issuer, audience, expiry
- [ ] No default `admin` or insecure fallback credentials
- [ ] Agent inherits caller permissions and cannot exceed them

### 10.3 Input and Injection

- [ ] All user and agent input validated and sanitized
- [ ] SQL/Cypher queries parameterized; no string concatenation
- [ ] No dynamic evaluation of model output (`eval`, `exec`, shell, raw SQL)
- [ ] File uploads validated by content type and size; stored outside web root
- [ ] Output from untrusted sources encoded before rendering

### 10.4 LLM and Agent Security

- [ ] System prompts treat external data as untrusted
- [ ] Tools are allowlisted per agent and validate inputs
- [ ] High-impact tool calls require human approval or explicit confirmation
- [ ] Tool credentials are scoped and not hard-coded
- [ ] Tool calls logged with enough detail for audit
- [ ] Model output not used for authorization decisions

### 10.5 Frontend

- [ ] No secrets in client code or Vite env
- [ ] CSP, HSTS, anti-XSS headers configured
- [ ] Tokens stored securely; no `localStorage`
- [ ] CORS restricted to known origins
- [ ] User-supplied HTML/markdown sanitized

### 10.6 Data and Infrastructure

- [ ] Database access uses least privilege; no admin connections from app
- [ ] PII/sensitive data minimized, encrypted, or pseudonymized
- [ ] Kubernetes manifests use non-root, read-only root FS, drop capabilities
- [ ] Network policies allow only required traffic
- [ ] Images built from minimal pinned base and signed

### 10.7 Testing

- [ ] Security unit tests for authorization and input validation
- [ ] Negative tests for prompt injection and tool abuse
- [ ] Regression tests for previous security bugs

---

## 11. Secure Coding Rules for All Agents

These are non-negotiable rules. Apply them in every task.

1. **Never trust input.** Validate all data from users, external APIs, files, and model outputs.
2. **Never trust model output.** Do not execute, query, or render model output as code.
3. **Least privilege everywhere.** Services, DB users, tools, and agents get only necessary permissions.
4. **Parameterize all database queries.** Use ORM or prepared statements. Never concatenate user input into SQL/Cypher.
5. **No secrets in code, config, logs, or frontend.** Use secret manager and env placeholders.
6. **Fail closed.** If authorization cannot be verified, deny access.
7. **Log security-relevant events.** Log auth failures, tool calls, state changes, and admin actions without sensitive data.
8. **Encode output.** Escape or sanitize before inserting into HTML, JSON, SQL, logs.
9. **Keep dependencies up to date.** Pin, scan, and patch.
10. **Design for auditability.** Every agent and service action must be traceable to a user and tool call.

---

## 12. Audit Guide for Security Agent

When auditing the platform, verify the following controls:

### Authentication & Authorization
- Are all API routes behind authentication except health checks?
- Are roles enforced with deny-by-default?
- Do agents validate user permissions on tool calls?
- Are tokens short-lived and securely stored?

### Secrets
- Run `gitleaks`/`trufflehog` over repo and image layers.
- Check Helm values and `.env` for real secrets.
- Verify secret manager integration and no default fallback.

### Dependencies and Images
- Confirm lockfiles and `trivy`/`grype` scans in CI.
- Inspect base images for non-root, distroless, pinned tags.
- Verify SBOM generation and image signing.

### LLM/Tool Security
- Review all system prompts for injection resistance.
- List all registered tools; compare to allowlist.
- Check tool input validation and audit logging.
- Attempt prompt injection against a staging agent.
- Confirm high-risk tools require human approval.

### Frontend/API Exposure
- Check CORS, CSP, secure cookies, and token storage.
- Inspect Vite env for accidental secret usage.
- Test for XSS in model output rendering.

### Data and Infrastructure
- Verify DB users are least privilege; no admin connection strings.
- Check network policies and Kubernetes security context.
- Confirm TLS and encrypted backups.

---

## 13. References

- OWASP Top 10 for LLM Applications
- OWASP ASVS
- OWASP Kubernetes Top 10
- MITRE ATT&CK for Kubernetes and LLM threats
- NIST SSDF
- CIS Kubernetes Benchmarks

---

## 14. Contact

Security team: `security@your-org.example`
Responsible disclosure: see `SECURITY.md` in repository root or contact the address above.
Do not include sensitive details in public issues.
