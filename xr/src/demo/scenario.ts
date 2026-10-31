/**
 * The demo: three tasks and what La Fabrique's agents did with each,
 * scripted from how the task worker runs a task (the Architect's brief, the
 * Developer's delivery, the Verifier's checks of what the daemon wrote, QA's
 * review, and the risk tier that holds high-risk work for a person).
 *
 * Times are milliseconds from the moment the task is launched. A task plays
 * out in under a minute, so the whole demo fits in a few minutes.
 */

import type { Delivery, RoomEvent, TaskState } from '../model';

export interface Cue {
  at: number;
  event: RoomEvent;
}

export interface DemoTask {
  id: string;
  title: string;
  /** One line on the task panel. */
  summary: string;
  script: Cue[];
  /** What happens when a person sends the delivery back. */
  rework?: Cue[];
}

const say = (
  at: number,
  taskId: string,
  role: 'Architect' | 'Developer' | 'QA' | 'Verifier' | 'ScrumMaster' | 'System',
  agent: string,
  message: string,
  type: 'status' | 'message' | 'error' = 'status',
): Cue => ({ at, event: { type, role, agent, message, taskId } as RoomEvent });

const start = (at: number, taskId: string, role: 'Architect' | 'Developer' | 'QA' | 'Verifier', agent: string, message: string): Cue => ({
  at,
  event: { type: 'agent_start', role, agent, message, taskId },
});

const finish = (at: number, taskId: string, role: 'Architect' | 'Developer' | 'QA' | 'Verifier', agent: string, message: string): Cue => ({
  at,
  event: { type: 'agent_complete', role, agent, message, taskId },
});

const state = (at: number, taskId: string, s: TaskState): Cue => ({ at, event: { type: 'task_state', taskId, state: s } });

const deliver = (at: number, taskId: string, delivery: Delivery): Cue => ({ at, event: { type: 'delivery', taskId, delivery } });

const RESET: Delivery = {
  runId: 'run-41',
  risk: 'high',
  riskReason: 'touches authentication (app/routers/password_reset.py)',
  files: [
    {
      path: 'backend/app/routers/password_reset.py',
      lines: [
        '+@router.post("/v1/auth/password/reset")',
        '+async def request_reset(req: ResetRequest, session: Session = Depends(get_session)):',
        '+    user = session.exec(select(User).where(User.email == req.email)).first()',
        '+    if user:',
        '+        token = issue_reset_token(user, ttl_minutes=15)',
        '+        send_reset_email(user.email, token)',
        '+    # Same answer either way: the endpoint never says who has an account.',
        '+    return {"status": "sent"}',
      ],
    },
    {
      path: 'backend/tests/test_password_reset.py',
      lines: [
        '+def test_unknown_email_gets_the_same_answer(client):',
        '+    assert client.post(URL, json={"email": "nobody@x.io"}).json() == {"status": "sent"}',
        '+',
        '+def test_token_expires_after_15_minutes(client, clock): ...',
      ],
    },
  ],
  checks: [
    { name: 'files_written', observed: '2 files, sha256 read back from disk match', ok: true },
    { name: 'tests_run', observed: 'pytest exit 0 (14 passed)', ok: true },
    { name: 'risk_tier', observed: 'high: authentication', ok: true },
  ],
};

const RESET_V2: Delivery = {
  ...RESET,
  runId: 'run-42',
  files: [
    RESET.files[0],
    {
      path: 'backend/tests/test_password_reset.py',
      lines: [
        ...RESET.files[1].lines,
        '+',
        '+def test_a_used_token_cannot_be_used_again(client): ...',
      ],
    },
  ],
  checks: [
    { name: 'files_written', observed: '2 files, sha256 read back from disk match', ok: true },
    { name: 'tests_run', observed: 'pytest exit 0 (15 passed)', ok: true },
    { name: 'risk_tier', observed: 'high: authentication', ok: true },
  ],
};

const CSV: Delivery = {
  runId: 'run-43',
  risk: 'low',
  riskReason: 'application code only',
  files: [
    {
      path: 'backend/app/routers/sprint_export.py',
      lines: [
        '+@router.get("/v1/sprints/{sprint_id}/export.csv")',
        '+def export_sprint(sprint_id: int, member=Depends(require_viewer)):',
        '+    rows = board_rows(sprint_id)',
        '+    return csv_response(["task", "state", "rework"], rows)',
      ],
    },
  ],
  checks: [
    { name: 'files_written', observed: '1 file, sha256 match', ok: true },
    { name: 'tests_run', observed: 'pytest exit 0 (9 passed)', ok: true },
    { name: 'risk_tier', observed: 'low', ok: true },
  ],
};

const CI: Delivery = {
  runId: 'run-44',
  risk: 'high',
  riskReason: 'changes the CI pipeline (.github/workflows/ci.yml)',
  files: [
    {
      path: '.github/workflows/ci.yml',
      lines: [
        ' jobs:',
        '   test:',
        '-    runs-on: ubuntu-latest',
        '+    runs-on: ubuntu-24.04',
        '     steps:',
        '-      - uses: actions/checkout@v4',
        '+      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4',
      ],
    },
  ],
  checks: [
    { name: 'files_written', observed: '1 file, sha256 match', ok: true },
    { name: 'tests_run', observed: 'not applicable: workflow change', ok: true },
    { name: 'risk_tier', observed: 'high: CI pipeline', ok: true },
  ],
};

export const DEMO_TASKS: DemoTask[] = [
  {
    id: 'reset',
    title: 'Password reset endpoint',
    summary: 'High risk: a person decides',
    script: [
      state(0, 'reset', 'in_progress'),
      start(500, 'reset', 'Architect', 'Ada', 'Reading the auth router before the Developer starts'),
      finish(4500, 'reset', 'Architect', 'Ada', 'Brief: same answer for unknown emails; tokens expire in 15 min'),
      start(5500, 'reset', 'Developer', 'Dev', 'Writing password_reset.py with the brief in the prompt'),
      say(11000, 'reset', 'Developer', 'Dev', 'Declared 2 files'),
      finish(13000, 'reset', 'Developer', 'Dev', 'Delivered run-41'),
      start(14000, 'reset', 'Verifier', 'Verifier', 'Hashing what the daemon wrote'),
      say(17000, 'reset', 'Verifier', 'Verifier', 'files_written: verified, 2 of 2'),
      finish(19500, 'reset', 'Verifier', 'Verifier', 'tests_run: pytest exit 0'),
      state(20000, 'reset', 'in_review'),
      start(20500, 'reset', 'QA', 'Quinn', 'Reviewing against the acceptance criteria'),
      finish(26000, 'reset', 'QA', 'Quinn', 'APPROVED: reset flow and expiry covered'),
      say(27000, 'reset', 'System', 'Risk tier', 'High risk (authentication): held for a person'),
      deliver(27000, 'reset', RESET),
      state(27500, 'reset', 'waiting_for_person'),
    ],
    rework: [
      say(500, 'reset', 'ScrumMaster', 'Sam', 'Sent back by a person: back to the Developer'),
      start(1500, 'reset', 'Developer', 'Dev', 'Adding the test the person asked for'),
      state(1500, 'reset', 'in_progress'),
      finish(7000, 'reset', 'Developer', 'Dev', 'Delivered run-42'),
      start(7500, 'reset', 'Verifier', 'Verifier', 'Hashing what the daemon wrote'),
      finish(10500, 'reset', 'Verifier', 'Verifier', 'tests_run: pytest exit 0 (15 passed)'),
      start(11000, 'reset', 'QA', 'Quinn', 'Reviewing the second attempt'),
      finish(15000, 'reset', 'QA', 'Quinn', 'APPROVED: the reused-token case is covered'),
      say(15500, 'reset', 'System', 'Risk tier', 'High risk (authentication): held for a person'),
      deliver(15500, 'reset', RESET_V2),
      state(16000, 'reset', 'waiting_for_person'),
    ],
  },
  {
    id: 'csv',
    title: 'CSV export of a sprint',
    summary: 'Low risk: QA closes it after one rework',
    script: [
      state(0, 'csv', 'in_progress'),
      start(500, 'csv', 'Developer', 'Dev', 'Writing sprint_export.py'),
      finish(6000, 'csv', 'Developer', 'Dev', 'Delivered run-43'),
      start(6500, 'csv', 'Verifier', 'Verifier', 'Hashing what the daemon wrote'),
      finish(9500, 'csv', 'Verifier', 'Verifier', 'files_written: verified, 1 of 1'),
      state(10000, 'csv', 'in_review'),
      start(10500, 'csv', 'QA', 'Quinn', 'Reviewing against the acceptance criteria'),
      say(15000, 'csv', 'QA', 'Quinn', 'NEEDS WORK: no test for an empty sprint'),
      start(16000, 'csv', 'Developer', 'Dev', 'Rework: adding the empty-sprint case'),
      finish(21000, 'csv', 'Developer', 'Dev', 'Delivered run-43b'),
      finish(24000, 'csv', 'Verifier', 'Verifier', 'tests_run: pytest exit 0 (10 passed)'),
      deliver(24000, 'csv', CSV),
      finish(28000, 'csv', 'QA', 'Quinn', 'APPROVED: low risk, closed without a person'),
      state(28500, 'csv', 'done'),
    ],
  },
  {
    id: 'ci',
    title: 'Pin the CI runner and actions',
    summary: 'High risk: the CI pipeline',
    script: [
      state(0, 'ci', 'in_progress'),
      start(500, 'ci', 'Architect', 'Ada', 'Checking which workflows run on pull requests'),
      finish(4000, 'ci', 'Architect', 'Ada', 'Brief: pin by commit SHA, keep the tag as a comment'),
      start(5000, 'ci', 'Developer', 'Dev', 'Editing .github/workflows/ci.yml'),
      finish(10000, 'ci', 'Developer', 'Dev', 'Delivered run-44'),
      start(10500, 'ci', 'Verifier', 'Verifier', 'Hashing what the daemon wrote'),
      finish(13500, 'ci', 'Verifier', 'Verifier', 'files_written: verified, 1 of 1'),
      state(14000, 'ci', 'in_review'),
      start(14500, 'ci', 'QA', 'Quinn', 'Reviewing the workflow change'),
      finish(19000, 'ci', 'QA', 'Quinn', 'APPROVED: every action pinned'),
      say(19500, 'ci', 'System', 'Risk tier', 'High risk (CI pipeline): held for a person'),
      deliver(19500, 'ci', CI),
      state(20000, 'ci', 'waiting_for_person'),
    ],
  },
];
