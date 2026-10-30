# Improvement plan for the web product (main, develop)

Written 2026-10-25 after reading two open-source projects again for ideas:
[block/buzz](https://github.com/block/buzz) (commit `9e8c9fc`, 2026-10-23)
and [Gentleman-Programming/gentle-ai](https://github.com/Gentleman-Programming/gentle-ai)
(commit `f61484d`, 2026-10-24). The Glassroom VR entry (`main_meta`,
`develop_meta`) is paused and out of scope here.

Each item names what the other project does, what changes in Le Fabrique and
why it serves [`POSITIONING.md`](POSITIONING.md): the product is the layer that
verifies agents' work and keeps the evidence. Sizes are S (a day or less), M
(a few days) and L (a week or more). Every item is one pull request.

## What the two projects are

- **buzz** is a self-hosted workspace where people and AI agents share
  channels, threads, repositories and workflows. Every message, approval and
  git event is a signed event in one log, scoped per community.
- **gentle-ai** is a command-line tool that configures the coding agent a
  person already uses. Its core rule is "verifying beats generating": the
  binary freezes a change, picks the review depth from it deterministically,
  binds each reviewer's result to the change's hash and records a receipt.

Both arrive where Le Fabrique already is: what an agent says is a claim, and
deterministic code decides. What they add is mostly rigour around that rule.

## Gaps confirmed in our code

| Gap | Where |
|---|---|
| Audit rows are signed one by one: no `company_id`, sequence or previous hash in the signed payload, so a deleted or reordered row is not detected | `backend/app/audit_signing.py` |
| The daemon's status turns "NATS down", "daemon answered with an error" and "no daemon" into the same `connected: false` | `services/workspace_daemon.py`, `routers/workspace.py` |
| A CI action runs from a moving branch | `security-scan.yml` uses `aquasecurity/trivy-action@master` |
| The task worker keeps growing | `services/task_worker.py`, 3,545 lines |
| Glassroom events are mostly untyped `status` messages | 31 `publish_glassroom` calls in `task_worker.py` |
| CLAUDE.md still calls `main.py` the file with all routes; it is 116 lines and the routes live in `routers/` | `CLAUDE.md` |
| `develop` is 263 commits behind `main` and holds 33 commits from May that `main` lacks | branches |

## Phase 0: housekeeping (all S)

1. **`develop` is where web pull requests land** (done 2026-10-25). Its 33
   commits of May 2026 were checked against `main`: the orchestration
   metrics they added are on `main` in `services/orchestration_metrics.py`,
   and the files only `develop` had (`Home`, `SprintBoard`,
   `SprintOpsCockpit`, the standalone Glassroom page, `routers/analytics.py`)
   are the ones the navigation rework removed on purpose. The old line is
   kept as `archive/develop-2026-05-02` and `develop` now equals `main`.
   Feature PRs land on `develop`; a release PR promotes it to `main` and a
   person merges it, as `CONTRIBUTING.md` already required ("agents do not
   merge to `main`"). `CONTRIBUTING.md` has a Branches section.
2. **Pin CI actions by commit SHA** (done 2026-10-25) with the version in a comment, and add
   Renovate (or Dependabot; Dependabot was chosen, `.github/dependabot.yml`) with digest pinning, a few days' delay after a
   release and no auto-merge of major updates. From buzz
   (`renovate.json`, `_ci-security.yml`). A verification product should not
   run code from a moving branch in its own CI.
3. **A PR template that separates claims from observations** (done 2026-10-25). Required
   sections: commands run with their exit status or CI link; what the agent
   exercised (a claim); what a person tested (an attestation the agent never
   ticks); which AI tool was used and for what. From buzz's `AGENTS.md`
   ("never mark this step done yourself") and gentle-ai's `AI_POLICY.md`. It
   writes into the template the rule POSITIONING adopted after PR #33.
4. **Fix CLAUDE.md's description of `main.py`** (done 2026-10-25).

## Phase 1: the evidence spine

5. **A hash chain per company for audit rows (M)** (done 2026-10-25; it also
   signs the KPI turn rows `orchestration_metrics.py` wrote with no signature). Each row gets
   `company_id`, a per-company `seq` and `prev_hash` in what is hashed, with a
   version prefix so existing rows keep verifying; writes take a per-company
   advisory lock; audit verification checks the whole chain, so a missing or
   reordered row fails. From buzz `crates/buzz-audit` (`hash.rs`,
   `service.rs`), which also cuts timestamps to the precision Postgres stores
   before hashing. Files: `audit_signing.py`, `models/audit.py`, the audit
   verification route, `database.py` for the new columns.
6. **A test that every table carries `company_id` (S)** (done 2026-10-25,
   `tests/test_tenant_scoping.py`), over
   `Base.metadata`, with an allowlist that states a reason for each global
   table (`users`, `companies`, help-desk tickets, outbox events). From buzz
   `crates/buzz-db/src/runtime/migration.rs`. POSITIONING calls tenant scoping
   expensive to retrofit; this keeps it from wearing away.
7. **The daemon is connected, absent or unknown (S)** (done 2026-10-25), with the reason, and
   the web app shows "unknown" as unknown. From buzz
   `docs/agent-availability.md`. It is POSITIONING's rule 7 ("unknown is not
   absent") applied to the daemon.
8. **Token counts as reported, unavailable or unsupported (S–M)** (done
   2026-10-25: the KPI turn rows and the Developer token average; the proxy
   marks each answer `reported` or `estimated` (`llm-proxy/usage.py`), so
   its characters/4 estimate for Gemini is no longer passed off as usage;
   `AgentRun` stores no token count, so nothing defaults to zero there), never a
   default zero, on `AgentRun`, the proxy's audit rows and
   `orchestration_metrics.py`. From gentle-ai `docs/telemetry.md` and its
   aggregate schema.

## Phase 2: how much verification a task gets

9. **A deterministic risk tier (M)** (done 2026-10-25, `services/risk.py`;
   the daemon reports neither file modes nor deletions, so executable bits
   and removed files are not classified yet). A Verifier check classifies each
   delivery from the files the daemon reports (authentication, secrets,
   shell scripts, executable bits, payments, migrations, deletions) as low,
   medium or high, with its reasons. Size never lowers the tier. An agent may
   raise it with a reason, never lower it. A high tier sends the task to a
   person through the inbox at any `autonomy_level`, autonomy level 3
   included: autonomy decides how much routine work goes without a person,
   and a delivery that touches authentication, secrets or payments is not
   routine. From gentle-ai `internal/reviewtransaction/risk.go` and
   `internal/cli/review_assess.go`.
10. **Acceptance criteria by reference, a verdict per criterion (M).** A
    backlog item's criteria are numbered and passed verbatim to the
    Developer's and QA's prompts; QA answers each one in a fixed format a
    parser checks, as the ScrumMaster's `DECISION … END` blocks are; the
    sprint list counts criteria left unanswered. From gentle-ai's ODD
    spec-by-reference (`odd/tasks/odd-spec-by-reference.md`), which credits it
    with fixing failures caused by paraphrased handoffs. The verdicts stay
    claims; what they add is that each one names the requirement it judges.
11. **An independent checker that replays task histories (M)** (done
    2026-10-25, `backend/app/history_check.py`, in the tests and at the end
    of the e2e run). It reads a
    task's comments, messages, verifications and approvals and rejects
    illegal histories: done without a verified delivery and an `APPROVED:`,
    a task carried over twice, a decision whose escalation does not exist.
    It must not import `services/board.py`, so a bug shared with the
    production readers cannot hide. Run it in the tests and at the end of
    `scripts/e2e/run.sh`. From buzz `crates/buzz-conformance`.
12. **Shadow evaluation for changes to the Verifier (M).** A new check or
    verdict rule first runs behind a flag, its result stored apart from the
    checks that decide, with an agreement count; with the flag off the
    output is identical. From gentle-ai
    `docs/architecture/rdd-shadow-evaluation.md`. The Verifier's own changes
    are then decided by numbers, like procedures are.
13. **Later: a refuter that confirms a claim by running a command (L).**
    When QA asks for rework citing a concrete failure, one reproducing
    command runs through `workspace.execute` and its exit status is recorded
    as an observation; where that cannot run, the run says so. Opt-in, like
    `DELIVERY_TESTS_ENABLED`, since it runs agent-written code. From
    gentle-ai `docs/review-integration.md` ("Refuter probe").

## Phase 3: what a person sees

14. **Typed Glassroom events (M).** Each event gets a closed class (message,
    file edit, command, verdict, error, other), a verb, an object, an
    outcome, a tone (read, write, admin) and whether it is a claim or an
    observation; a running action updates its own row; unknown events show
    as a plain row rather than vanish. From buzz `VISION_ACTIVITY.md` and
    `desktop/src/features/agents/ui/agentSessionTypes.ts`. Files:
    `services/glassroom.py`, the `publish_glassroom` calls, the frontend's
    Glassroom store and component.
15. **Every refusal names the next step (M).** A test collects the
    `HTTPException` details under `routers/`; each must name what to do, or
    carry a marker from a closed list (a person's authority, knowledge only
    the operator has), or sit in a baseline that may only shrink. From
    gentle-ai `internal/cli/refusal_resolution_ratchet_test.go`. The daemon's
    503 with start instructions is the model to follow.

## Phase 4: contracts and guardrails for contributors

16. **Versioned contracts with fixtures (M).** A `contracts/` folder with
    JSON schemas and example files for the run-ingest payload outside
    producers send, the fixed answer formats (`DECISION`, `PROCEDURE`, the
    Reviewer agent's) and the Glassroom events, each validated in pytest.
    From gentle-ai `contracts/review-integration/v2/`. Outside producers are
    central to the direction and need a contract that does not move under
    them.
17. **An adversarial fake model in the e2e run (S)** (done 2026-10-25). `scripts/e2e/fake_llm.py`
    refuses requests that break the loop's order, for example a QA review
    prompt for a task with no `files_written` observation yet, so the run
    fails at the boundary instead of in an assertion afterwards. From
    gentle-ai `docs/testing-agents-deterministically.md`.
18. **Ratchets for file size and dead code (S each).** File size done
    2026-10-25 (`scripts/check_file_sizes.py`, 600 lines, baseline in
    `scripts/file_size_baseline.json`, `.github/workflows/file-sizes.yml`);
    the dead-code ratchet still to follow. A file over its size
    limit may not grow (only changed files are checked); a new unreachable
    function fails CI against a baseline (`vulture`). From buzz
    `scripts/check-file-sizes-core.mjs` and gentle-ai
    `scripts/deadcode-ratchet.sh`. They keep `REFACTORING_PLAN.md` from losing
    ground, and catch the class of dead code POSITIONING records (PR #12).
19. **Review-proven rules in CLAUDE.md (S).** Recurring defects from our own
    pull requests and code reviews, each with the PRs that showed it and a
    count, not an estimate. From buzz's "Review-Proven Rules" in `AGENTS.md`
    and `TESTING.md`. It applies procedures measured by metrics to the people
    and agents building Le Fabrique.

## To check before planning

- **Where memory entries come from.** buzz's draft information-flow design
  tags each memory entry with the audience it came from. The Support and
  Reviewer agents read untrusted text (a public form, an outside producer's
  artifact). Check whether such text can reach the Developer's prompt
  through memory search unmarked; if it can, tag entries by origin and wrap
  untrusted ones as data.

## Considered and left out

- **Agents signing their own events with their own keys** (buzz): the server
  would hold the keys, so the signatures would prove nothing; server-computed
  digests already cover this.
- **Nostr as the event protocol, remote agent bodies on Kubernetes, TLA+
  specs** (buzz): costly and not needed; item 11 gets most of the value of
  the specs.
- **Feature flags per company** (buzz): useful once the Support and Reviewer
  agents need comparing per company, not before.
- **Installing configuration into many agent CLIs, the agent builder, the
  receipt lifecycle** (gentle-ai): local-tool machinery; the console
  assistant probe and run versions already cover our case.
- **Engram's git-file memory sync** (gentle-ai): Le Fabrique's memory is
  per company on a server.
- **gentle-ai's ban on AI `Co-Authored-By` lines**: kept as they are. For a
  product whose point is knowing who produced what, a commit that says an
  agent wrote it is evidence, not noise; the PR template (item 3) adds what
  was verified and by whom.

## Order

Phase 0 first: it is small and decides where the rest lands. Then items 5
to 8 (the evidence spine), 9 to 12, 14 and 15, and 16 to 19 alongside as
small PRs. Item 13 waits until 9 and 11 are in.

## Decisions taken (2026-10-25)

The owner delegated these three:

1. **`develop`** is where web pull requests land; its May line is archived
   and it was reset to `main`. Releases to `main` are merged by a person
   (item 1).
2. **A high risk tier needs a person at every autonomy level**, level 3
   included (item 9).
3. **AI co-author lines stay** in commits (see "Considered and left out").
