/**
 * The room's state, built only from events.
 *
 * The events have the same shape as the ones the backend publishes on the
 * Glassroom stream (`backend/app/services/glassroom.py`): a `type`
 * (`agent_start`, `agent_complete`, `status`, `message`, `error`), the `agent`
 * and its `role`, and a `message`. The demo replays recorded ones; live mode
 * reads the real stream. Two event types exist only in the room: `delivery`,
 * which carries the files a run wrote and the Verifier's checks, and
 * `decision`, a person's approval or rejection.
 */

export type Role = 'Architect' | 'Developer' | 'QA' | 'Verifier' | 'ScrumMaster';

export const ROLES: readonly Role[] = ['Architect', 'Developer', 'QA', 'Verifier', 'ScrumMaster'];

export type AgentState = 'idle' | 'working' | 'done' | 'error';

export type Risk = 'low' | 'medium' | 'high';

export interface FileChange {
  path: string;
  /** Unified-diff lines, each starting with '+', '-' or ' '. */
  lines: string[];
}

export interface Check {
  name: string;
  /** What the Verifier observed, never what the agent claimed. */
  observed: string;
  ok: boolean;
}

export interface Delivery {
  runId: string;
  files: FileChange[];
  checks: Check[];
  risk: Risk;
  riskReason: string;
}

export type RoomEvent =
  | { type: 'agent_start' | 'agent_complete'; role: Role; agent: string; message: string; taskId: string }
  | { type: 'status' | 'message' | 'error'; role: Role | 'System'; agent: string; message: string; taskId: string }
  | { type: 'delivery'; taskId: string; delivery: Delivery }
  | { type: 'task_state'; taskId: string; state: TaskState }
  | { type: 'decision'; taskId: string; approved: boolean; reason: string };

export type TaskState =
  | 'queued'
  | 'in_progress'
  | 'in_review'
  | 'waiting_for_person'
  | 'done'
  | 'sent_back';

export interface AgentView {
  role: Role;
  name: string;
  state: AgentState;
  /** Most recent lines, newest last. */
  lines: string[];
}

export interface TaskView {
  id: string;
  title: string;
  state: TaskState;
  delivery?: Delivery;
  decision?: { approved: boolean; reason: string };
}

export interface RoomState {
  agents: Record<Role, AgentView>;
  tasks: Record<string, TaskView>;
  /** The task whose delivery the result panel shows. */
  focus?: string;
  log: string[];
}

/** How many lines an agent panel keeps. */
export const AGENT_LINES = 4;
/** How many lines the room's log keeps. */
export const LOG_LINES = 6;

const NAMES: Record<Role, string> = {
  Architect: 'Ada',
  Developer: 'Dev',
  QA: 'Quinn',
  Verifier: 'Verifier',
  ScrumMaster: 'Sam',
};

export function initialState(tasks: { id: string; title: string }[]): RoomState {
  const agents = {} as Record<Role, AgentView>;
  for (const role of ROLES) agents[role] = { role, name: NAMES[role], state: 'idle', lines: [] };
  return {
    agents,
    tasks: Object.fromEntries(tasks.map((t) => [t.id, { ...t, state: 'queued' as TaskState }])),
    log: [],
  };
}

function push(lines: string[], line: string, keep: number): string[] {
  return [...lines, line].slice(-keep);
}

/** Apply one event. Pure: returns a new state and leaves `state` untouched. */
export function reduce(state: RoomState, event: RoomEvent): RoomState {
  const task = state.tasks[event.taskId];
  if (!task) return state;
  switch (event.type) {
    case 'agent_start':
    case 'agent_complete':
    case 'status':
    case 'message':
    case 'error': {
      const next = { ...state, log: push(state.log, `${event.agent}: ${event.message}`, LOG_LINES) };
      if (event.role === 'System') return next;
      const agent = state.agents[event.role];
      const agentState: AgentState =
        event.type === 'agent_start'
          ? 'working'
          : event.type === 'agent_complete'
            ? 'done'
            : event.type === 'error'
              ? 'error'
              : agent.state;
      return {
        ...next,
        agents: {
          ...state.agents,
          [event.role]: { ...agent, state: agentState, lines: push(agent.lines, event.message, AGENT_LINES) },
        },
      };
    }
    case 'delivery':
      return {
        ...state,
        focus: event.taskId,
        tasks: { ...state.tasks, [task.id]: { ...task, delivery: event.delivery, decision: undefined } },
      };
    case 'task_state':
      return { ...state, tasks: { ...state.tasks, [task.id]: { ...task, state: event.state } } };
    case 'decision':
      return {
        ...state,
        log: push(
          state.log,
          `You: ${event.approved ? 'approved' : 'sent back'} ${task.title}${event.reason ? ` (${event.reason})` : ''}`,
          LOG_LINES,
        ),
        tasks: {
          ...state.tasks,
          [task.id]: {
            ...task,
            state: event.approved ? 'done' : 'sent_back',
            decision: { approved: event.approved, reason: event.reason },
          },
        },
      };
  }
}

/** A delivery waits for a person only when its task does. */
export function awaitingDecision(state: RoomState): TaskView | undefined {
  const focused = state.focus ? state.tasks[state.focus] : undefined;
  return focused?.state === 'waiting_for_person' ? focused : undefined;
}
