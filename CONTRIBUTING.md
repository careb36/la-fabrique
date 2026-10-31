# Contributing to La Fabrique

La Fabrique is an open-source (Apache 2.0) multi-agent orchestration platform: a React web
app, a FastAPI control plane, and LangGraph-based sprint orchestration with
first-class observability.

This document is the single source of truth for **proposing, reviewing, and
merging changes** — for humans and for AI agents. If you are an agent, read
§2 before you open a PR.

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
| AI agents | Draft specs, implement, review, verify, merge | Yes (any PR, head green only) |
| Human Owner | Ownership, escalation, final call | Yes |

---

## 2. Non-negotiables

1. **No secrets in the repo.** Ever. Use the secret manager. No workflow scans
   for secrets, so nothing will catch a committed key: check before you commit.
2. **Third-party IP.** Do not paste code, prompts, or designs from La Fabrique into
   third-party tools without Security sign-off. No new dependency without
   Security review.
3. **`main` is always releasable.** Nothing merges to `main` with a red pipeline.
4. **Every change traces to an issue.** PRs without a linked issue are closed.
5. **Agents merge pull requests** — their own and each other's — once every
   check on the head commit is green. No PR waits for a human signature. What
   still does not happen: merging a red or still-running head, merging a head
   that moved after it was verified, or weakening branch protection to force a
   merge through.
6. **Tests and observability ship with the change**, not after it.

### Licensing of contributions

La Fabrique is released under the [Apache License 2.0](LICENSE). By opening a
pull request you agree that your contribution is licensed under the same terms
(inbound = outbound, no separate CLA). Only contribute code you have the right
to submit: no copied code from a project whose licence is incompatible with
Apache 2.0, and keep third-party notices intact.

---

## 3. Local setup

See [`README.md`](README.md) — Installation for the full stack and the
workspace daemon. Per-project commands (backend tests, frontend gates, lint)
are in [`CODING_STANDARDS.md`](CODING_STANDARDS.md).

---

## 4. Branches

| Branch | What it is | Who merges into it |
|--------|-----------|--------------------|
| `main` | The web product, and the default branch | An agent or a person, with the head green (rule 5) |
| `fusion` | The NVIDIA × Nebius hackathon submission | As for `main` |
| `meta-vr` | La Fabrique XR, the Meta VR Start Developer Competition entry (`xr/`); GitHub Pages publishes from it | As for `main` |
| `archive/*` | Old lines of work kept for reference; nothing merges into them | Nobody |

Work is trunk-based: one branch cut from `main`, one pull request into `main`,
merged with a merge commit rather than a squash so the history keeps its shape.
There is no `develop` integration branch — it only ever mirrored `main`, and it
was retired on 2026-10-29 along with the release pull request it existed for.
`archive/develop-2026-05-02` keeps the `develop` of May 2026, whose useful work
`main` had already rewritten. `main` carries none of `vr/`.
