# Positioning: what le-fabrique is for

> **Status: adopted, 2026-09-19; amended 2026-10-18.** This is the project's
> direction, confirmed by the repository owner. It is the written form of the
> argument in issue #38. The code findings cited here are verified and
> reproducible; the market reading is a judgment, and remains open to revision
> if the market moves. The [amendment](#amendment-2026-10-18-a-self-managed-company-of-agents)
> at the end adds the owner's direction that the factory runs itself as a
> company of agents; it keeps every design rule below.

## The one-line version

**The agents are interchangeable and are not the product. The product is the
layer that observes them, measures them, verifies them, and leaves an
evidentiary record.**

## What changed

le-fabrique was built on the bet that a simulated scrum team — PO, Architect,
ScrumMaster, Developer, QA, SecOps, TechWriter, each a node in a LangGraph —
would produce working software. That bet was reasonable when models were weak at
long-horizon work and decomposing into mutually-critiquing roles was a plausible
way to compensate.

The field went the other way. The scaffolding that turned out to matter is
**tools, context and verification**, not personas. The systems that work are one
strong agent with good tool access and a feedback loop against reality — tests,
compiler, CI. None of them simulate a team.

There are structural reasons, not just fashion:

- A persona adds no capability the base model lacks.
- Every handoff loses context and adds latency and cost.
- Errors compound along the chain.
- "The QA agent reviews the Developer agent" is weaker than running the tests.
  A node that emits `APPROVED` is not evidence of anything. A green pytest is.

## The scarce thing is verification

Generated code is abundant and cheap. What is scarce is a trustworthy answer to:

> Did this agent actually do what it says it did?

This repository's own history is the evidence:

- **PR #27** was merged with an entirely empty diff while its body described a
  complete Fernet implementation. It auto-closed the issue on the strength of
  that claim.
- **PR #33**'s body asserted a green build while CI was red.
- **PR #18** shipped a regression that swapped i18next's `defaultValue` for a
  `||` chain — a missing key returns the key itself, which is truthy, so
  untranslated strings rendered as raw dotted keys.
- **PR #12** revealed the orchestration health KPIs had returned zero since they
  were written, meaning nobody had ever confirmed the agent loop did anything.

In none of these cases was the agent adversarial. It was sincerely wrong, or
reporting an intention as an outcome. That is the normal case, and it is exactly
what a verification layer catches. Every one of them was caught by a human
reading the actual artifact. Nothing in this system would have noticed.

## The design rules that follow

These are the constraints that make the layer worth anything. They are easy to
violate by accident and expensive to restore once violated.

1. **A claim and an observation must never share a field.** The entire value is
   being able to say "the agent asserted X; we observed Y". Merging them
   destroys it.

2. **An agent's report of its own verification is a claim, never an
   observation.** Test results count only when they come from an independent
   source — a CI check-run conclusion, a recorded exit status.

3. **`unverifiable` is a real verdict.** It is distinct from `verified` and from
   `refuted`, and must never collapse into either. Most honest answers about
   third-party agent work are `unverifiable`, and a system that cannot say so
   will lie to stay useful.

4. **Refutation must be load-bearing.** A verifier that only ever confirms is
   theatre. Build the refutation path first.

5. **Do not use an LLM to decide whether a claim holds.** That reintroduces the
   unreliability being measured. Deterministic checks decide; a model may
   summarise a refutation for a human afterwards.

6. **Never accept a digest, hash or signature from the party being recorded.**
   Compute it server-side. This was already violated: `decision_signature` is
   documented as a non-repudiation hash and is taken verbatim from the request
   body (issue #39).

7. **Unknown is not absent and is not false.** A third-party agent that does not
   report its model is not one that ran no model. Do not default unknowns.

## What this keeps

| Asset | Why |
|---|---|
| `audit_log` + `decision_signature` | The evidentiary spine. Right shape; the signature needs to become real. |
| Neo4j Engram nodes | Immutable per-decision lineage with timestamps. Genuinely valuable and poorly served in regulated industries. |
| LLM proxy token budgets | A single chokepoint for control and metering. |
| Multi-tenant `company_id` scoping and RBAC | Expensive to retrofit later. |
| `services/orchestration_metrics.py` | Already a measurement contract; generalises from "our agents" to "any agent". |

## What this demotes

| Asset | Disposition |
|---|---|
| The 7-role persona graph (`backend/agents/graph.py`) | Behind a flag, off by default. One possible *producer*, with no privileged status. |
| `design → generate → execute → burn` as the only pipeline | Joined by ingestion of externally-produced work. |
| The internal `task_queue` HITL path | Rebuilt on external agent events. The table is currently dead — nothing inserts into it. |
| `GlassRoom` | Still reachable, no longer the default view. Watching agents narrate is the least valuable screen. |

Nothing here is deleted. Demoting rather than removing keeps the option open,
and it makes the persona approach *measurable*: once internal-graph runs and
external-agent runs land in the same table under the same verification, "does
role decomposition actually help?" stops being a matter of opinion.

## Why this is defensible

Competing on orchestration against the model vendors and IDE makers is
unwinnable at this size — they control the model and the editor.

Governance, auditability and verification of AI-generated code, for regulated
industries, is a different contest. The large vendors are structurally slower
there, it is not urgent for them, and half the infrastructure already exists
here: Engram lineage, per-company RBAC, token budgets, and a proxy that is
already the single point of control.

"Who generated this code, with which model, from what context, who approved it,
and prove it" is a question that is going to be mandatory, and almost nobody
answers it today.

## Working agreements this implies

- CI is not optional. A verification product whose own tests do not run is not
  credible. See issue #36.
- Never claim a green build. State exactly what was run. This rule exists
  because it was broken (PR #33).
- Local verification is not a substitute for CI, and neither is a passing test
  suite a substitute for reading the diff.

## Tracking

Issue #38 is the epic. Child issues cover the evidentiary foundation, removal of
dead paths, and the product surface.

## Amendment (2026-10-18): a self-managed company of agents

The owner set this direction on 2026-10-18:

> La Fabrique has to manage itself; AI agents are configured for everything.
> They should communicate as in a real company: people follow rules and
> procedures, but they talk to each other, and that is how they learn and
> improve.

### How it fits the rules above

A real company is the model, including its audits. In a company that works,
people talk, propose, review and argue. A colleague saying "looks good" is
still not proof the work was done, and records settle disputes: the
accounts, the test report, the signed delivery note.

The owner chose the same arbiter here: **the evidence has the last word.**
Agents converse, propose and review, but a task is done only when an
observation shows it (tests, CI, files read back from disk). So the
amendment adds an organisation on top of the verification layer and
replaces none of it.

- A message between agents is a **claim**. It never becomes an observation
  (rules 1 and 2), however many agents agree with it.
- A reviewer's `APPROVED:` closes a task only after the deterministic
  delivery gate has passed. The review loop already enforces this.
- Agents may **propose** changes to how they work. Whether a change helped is
  decided by deterministic metrics: refutation rate, rework cycles, blocked
  tasks. A model's judgement does not decide it (rule 5).

### The design

1. **Procedures as data.** Rules and procedures become versioned records per
   role, for example how to deliver a task, how to review one, how to handle
   a ticket. Today they are free-text `system_prompt`s. Each agent's prompt is
   built from its role and the procedures in force.
2. **Communication that is kept.** Threads per task, sprint and ticket, and
   messages addressed between roles: ask, propose, escalate, inform. They are
   persisted and shown in the UI. This generalises what exists today: the
   comment thread on each task and the Architect consultation.
3. **Learning through retrospectives.** When a sprint closes, the agents read
   what happened (verdicts, refutations, why work was sent back) and propose
   procedure changes.
   - The company's `autonomy_level` decides whether a change is adopted
     directly or needs a human's approval.
   - The metrics of the following sprints decide whether it is kept. A change
     that makes them worse is reverted.
4. **Self-management.** Operating the platform is also done by agent roles.
   For example, a Support agent works the help desk with its own identity.
   Humans set rules, autonomy and budgets; the agents do the work.

### Order of work

1. **Memory that reaches the agents** (done with this amendment). The task
   worker searched past decisions without a `company_id`, so the search
   always came back empty. The Neo4j search was also limited to the agent's
   own role, so the ScrumMaster's retrospectives never reached the others.
   Both are fixed. Each task prompt now also carries **Lessons from Recent
   Sprints**: the retrospective counts and the review requests from the
   company's last two completed sprints, read from the board in Postgres, so
   they work without Neo4j. The prompt labels review requests as reviewers'
   opinions, not facts. It leaves out the verifier's infrastructure messages
   and keeps its failed test runs, which are observations.
2. **Messages between roles, persisted and visible** (done). Each hand-over is
   an `AgentMessage` with sender, recipient and kind (question, answer,
   handoff, request, decision, escalation, retrospective). The sprint's
   Conversation tab and the task page show them. Messages sit beside the
   evidence and never replace it.
3. **Versioned procedures, proposed at retrospectives and measured** (done).
   - A `Procedure` belongs to a role (or to every role) and is part of that
     role's prompts while active.
   - After a sprint with rework or blocked tasks, the ScrumMaster proposes up
     to two, in a fixed format a parser checks. Autonomy level 3 adopts them
     at once; below that, a Manager decides.
   - Two completed sprints after adoption, the board's numbers (rework per
     task, share of blocked tasks) keep the procedure or revert it to the
     version it replaced. A procedure with no sprints to compare with is
     marked unmeasured, not kept.
   - The ScrumMaster proposes knowing what earlier procedures did: kept,
     reverted or unmeasured with the board's numbers, or rejected by a
     person. The same text as one reverted or rejected is not recorded
     again from its proposals, so autonomy cannot re-adopt what the numbers
     or a person already turned down; a person can still bring it back.
4. **Operational agents**: the first one is done. The **Support agent** triages
   new help-desk tickets with its own identity (`Support agent`).
   - It suggests a severity and a category and writes the reporter a first
     reply, all in a fixed format a parser checks.
   - Its suggestions sit beside what the reporter chose and never overwrite it,
     and a support admin decides.
   - The ticket text comes from a public form, so the prompt treats it as data
     and the agent has no tools.
   - It is enabled with `SUPPORT_AGENT_ENABLED`. Next candidates: agents for
     the other tasks people still do by hand.
   - A support admin's decision on severity and category is stored apart from
     both claims, and the agent is measured against it: how often its
     suggestion matched, beside how often the reporter's own choice did. The
     numbers go into its next prompt and the help desk shows them.
   - The baseline is only what reporters actually chose: the form presets
     no impact and asks for no category, so the platform fills in neither as
     if it were theirs. An answer the agent could not give counts as a miss, and is
     counted, so a silent agent does not look accurate.
   - The second is the **Reviewer agent**. It reads the evidence of a run
     another producer sent (the Verifier's checks, the claims, the artifact
     as data) and suggests approve or reject with a category and a reason,
     in a fixed format a parser checks. The suggestion is stored on the run
     apart from the approval, and only a Manager's approval decides. It is
     measured against those decisions, with the Verifier's deterministic
     verdict as the baseline it has to beat (verified → approved, refuted →
     rejected), and the numbers go into its next prompt.
5. **The loop closes** (done). What the first four steps left open was what
   happens to work the agents give up on.
   - A sprint closes when every task is settled: done, or blocked until a
     person acts. Before, a blocked task held the sprint open for good, so
     there was no retrospective, no proposal and no measurement; the blocked
     share could only ever be measured over sprints that had none.
   - The text checks before review ask for rework with the reason, like a
     reviewer, instead of blocking a task on a judgement about form; after
     the rework limit they block it and escalate to the ScrumMaster.
   - `GET /v1/inbox` and the Review page are a person's queue: blocked
     tasks, procedure proposals waiting, runs nobody decided on. A Manager
     sends a task back to work or carries it into the next sprint with what
     blocked it; at autonomy level 3 the company carries it over on its own,
     once. A task that blocks twice stays for a person.
   - The escalation is answered. The ScrumMaster reads what blocked a task
     and decides, in a fixed format a parser checks, between another attempt
     with a brief for it or leaving it to a person. The decision is a
     message, so a claim: the brief goes into the next attempt's prompt, the
     company does not carry over on its own what the ScrumMaster left to a
     person, and a person sees the triage in the inbox and still decides.
   - The sprint list shows blocked tasks and rework requests per sprint, so
     whether the company is learning is visible without opening anything.
   - Second attempts are measured: how many carried tasks got done, with and
     without the ScrumMaster's brief. The same numbers, counted from the
     boards, go into the ScrumMaster's next triage, so its judgement is
     confronted with the outcome of its earlier calls rather than with its
     own account of them.
   - Console-assistant advice is measured the same way: tasks that got it
     against tasks that did not, done and rework per group, counted from the
     boards. The advice stays prompt context; whether it helps is a number.
   - So is the Architect's brief, which a Developer asks for before a
     design-sensitive or reworked task: briefed tasks against the rest, a
     briefed task's rework counted from the brief on. The Architect is told
     those numbers when it is asked again. The brief is a claim, and it is
     never read as a verdict on the task.

### What this changes in the tables above

The 7-role persona graph stays a producer behind a flag. The company
described here lives in the task worker's loop, which is already the path
work takes. Roles return as an **organisation**: who does what, under which
procedure, talking to whom. They do not return as a claim that personas add
capability. Whether that organisation helps is measurable in the same table
and under the same verification as everything else.
