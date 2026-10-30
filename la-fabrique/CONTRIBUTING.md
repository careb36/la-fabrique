# Contributing to La Fabrique

La Fabrique is an open-source (Apache 2.0) multi-agent orchestration platform: a React web
app, a FastAPI control plane, and LangGraph-based sprint orchestration with
first-class observability.

This document is the single source of truth for **proposing, reviewing, and
merging changes** — for humans and for AI agents. If you are an agent, read
§10 before you open a PR.

- Normative: `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, accepted ADRs.
- Precedence: `SECURITY.md` > accepted ADR > `CONTRIBUTING.md` > tooling default.
- Questions: open a `question` issue or ask in `#fabrique-eng`.

---

## 1. Who does what

| Role | Responsibility | Merge authority |
|------|----------------|-----------------|
| Product Owner | Sprint scope, acceptance criteria, prioritization | No |
| Architect | System design, contracts, ADRs, cross-cutting review | Yes (design areas) |
| Scrum Master | Sprint flow, status hygiene, unblocking, escalation | No |
| Security | Threat model, secrets, dependency & data-handling review | Yes (security-sensitive) |
| Developers | Implementation, tests, observability | Yes (own area, after review) |
| QA | Verification against acceptance criteria | No |
| AI agents | Draft specs, implement, review, verify — per §10 | **Never** (see §10.2) |
| Human Owner | Final authority on `main` | Yes |

---

## 2. Non-negotiables

1. **No secrets in the repo.** Ever. Use the secret manager. No workflow scans
   for secrets, so nothing will catch a committed key: check before you commit.
2. **Third-party IP.** Do not paste code, prompts, or designs from La Fabrique into
   third-party tools without Security sign-off. No new dependency without §7.4.
3. **`main` is always releasable.** Nothing merges to `main` with a red pipeline.
4. **Every change traces to an issue.** PRs without a linked issue are closed.
5. **Agents do not merge to `main`.** A human merges every PR (§10.2).
6. **Tests and observability ship with the change**, not after it (§12).

### Licensing of contributions

La Fabrique is released under the [Apache License 2.0](LICENSE). By opening a
pull request you agree that your contribution is licensed under the same terms
(inbound = outbound, no separate CLA). Only contribute code you have the right
to submit: no copied code from a project whose licence is incompatible with
Apache 2.0, and keep third-party notices intact.

---

## 3. Local setup

Not written yet: setup lives in `README.md` and `CLAUDE.md` until this
section is.

---

## 4. Branches

| Branch | What it is | Who merges into it |
|--------|-----------|--------------------|
| `develop` | Where web-product pull requests land | An agent or a person, with the pipeline green |
| `main` | The released web product | A person, through a release pull request from `develop` (rule 5 above) |
| `develop_meta`, `main_meta` | The Glassroom VR entry for the Meta VR Start Developer Competition, the same pair for `vr/` | As for `develop` and `main` |
| `archive/*` | Old lines of work kept for reference; nothing merges into them | Nobody |

A release pull request is merged with a merge commit, not a squash, so the
next release stays a fast-forward. `main` and `develop` carry none of `vr/`.
`archive/develop-2026-05-02` holds the `develop` of May 2026, whose useful
work `main` had already rewritten.
