# La Fabrique — guide for managers

For the person who owns the outcome rather than the code. It explains what the
system does, what you decide, and what it will not do for you. No command line
needed: everything here happens in the dashboard.

For installation, see [`README.md`](README.md). For the technical design, see
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## The idea in one paragraph

You set a goal for a sprint. A team of AI agents plans the work, writes it, and
delivers it back to you with evidence of what it actually did: which files were
written, with which content hash, and whether the tests ran. The product is not
the code generation — any tool can generate code. The product is that every
delivery is checked against evidence the delivering agent cannot forge, and that
the result is recorded so you can audit it later.

That distinction decides how you use it. You are not asked to read code and trust
it. You are asked to read a verdict.

## What a sprint looks like

1. **Plan.** You describe the goal and a scope size. The planner turns it into
   backlog items with acceptance criteria.
2. **Dispatch.** The items go out as tasks. Each one is picked up by an agent
   with a role: product owner, architect, developer, QA, technical writer.
3. **Work.** The agent produces a change and hands it to the workspace daemon,
   the small program on your machine that writes files into your project folder.
4. **Verify.** Each claim in the delivery is compared with what the daemon
   observed. The result is one of three verdicts:
   - **Verified**: every claim is backed by evidence.
   - **Refuted**: the evidence contradicts a claim.
   - **Unverifiable**: there is nothing to check the claim against.
5. **Review.** A refuted or unconfirmed delivery goes back for rework without
   asking a model. Otherwise the QA agent reads the delivery against the task;
   if it finds a problem, the task goes back with the specific finding, and only
   an explicit approval closes it.
6. **Decide.** A person decides what the loop does not: tasks blocked after
   repeated rework, approved deliveries that touch high-risk areas, and runs
   sent by other producers. A decision on a run is recorded in the audit log,
   signed when the installation has an audit signing key.

`Unverifiable` is not a soft pass. An agent that delivers work nobody witnessed
has not shown its work, and the system says so rather than guessing.

## The screens

| Screen | What you do there |
|---|---|
| **Evidence** (the landing page) | The list of agent runs with their verdicts. Start here. Click a run to see each check and its observation. |
| **Sprints** | Every sprint with its state. Open one to see the board, the live stream and its analytics. |
| **Board** | Tasks by column, with the verdict badge on each delivery. Move or stop work. |
| **Live** | What the agents are doing right now, streamed as it happens. |
| **Analytics** | Sprint health and the trend of the team's own learning. |
| **Quotas** | Token budget per business unit, and how much of it is spent. |
| **Members** | Who in your company has access, and with which role. |
| **Procedures** | Rules the team learnt from its own retrospectives. It proposes, you adopt or reject. |
| **Lineage** | Why a decision was taken: the chain of records behind it. |
| **GitHub** | Which repository the company is bound to. |
| **Help desk** | Support tickets. An agent triages them; a person decides. |

## What you decide

Three settings shape how much the team does on its own.

- **Autonomy level** (1 to 3, 2 for a new company). At level 3, when a sprint
  closes the team opens a self-improvement sprint by itself (carrying the closed
  sprint's blocked tasks into it, once each) and adopts the procedures the
  ScrumMaster proposes at once. Below 3, a person starts sprints and adopts or
  rejects each proposal.
- **Approvals.** A person with the Manager role decides on the runs that matter.
  The decision carries your name and, if you reject, a category and a text
  explaining why.
- **Quotas.** A token budget per business unit. The gateway enforces it before
  each model call, so the ceiling holds during the sprint, not after the invoice.

## Roles

| Role | What it can do |
|---|---|
| **Owner** | Everything, including company settings and members |
| **Manager** | Approve deliveries, verify runs, adopt procedures |
| **Viewer** | Read the board, the evidence and the analytics |

Company data is scoped by company: a member of one company cannot see another's
sprints, runs or evidence.

## What it will not do

Being clear about this is part of the product.

- **It does not scan your code for security problems on its own.** There is a
  SecOps role prompt, but no vulnerability scanner runs as part of a sprint. Use
  a scanner.
- **It does not deploy.** It writes files and runs the commands the daemon is
  allowed to run in the workspace you opened. Releasing is yours.
- **It does not promise tests pass because an agent says so.** A claim about
  tests counts only with independent evidence, such as the result of a CI run.
- **It does not grade work with a model.** The checks are deterministic
  comparisons. A model writes the work; it never decides whether the work holds.
- **It is not free-running by default.** A new company starts at autonomy
  level 2. Even at level 3, an approved delivery that touches authentication,
  secrets, payments or the CI pipeline waits for a person, and the evidence page
  still shows every verdict.

## Reading a verdict

Open a run and read the checks in order. Each has a name, an outcome and one
sentence of observation.

- `artifact_nonempty`: was anything delivered at all.
- `claimed_files_present`: do the files the agent named appear in what it sent.
- `claimed_tests_evidenced`: does independent evidence support the claim about
  tests.
- `files_written`: did the daemon report writing those files, with the same
  content hash the backend sent.
- `tests_run`: what the test command actually returned.
- `risk_tier`: how much a person should look at this, from low to high, with the
  reasons.

If a check is `unverifiable`, the observation says what was missing. That is
usually a wire that is not connected, not a bug in the agent.

## Getting help

Open a ticket from the help desk screen. When the installation enables it, the
support agent attaches a first reading; a support admin sees every ticket and
can download the logs. Include
what you were doing and what you expected.
