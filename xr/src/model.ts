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
  /** The agent that started work most recently: the task is in its hands. */
  active?: Role;
  /** The Verifier's confirmations on the work in hand, at most three. */
  seals: number;
}

/** How many lines an agent panel keeps. */
export const AGENT_LINES = 4;
/** The Verifier's checks a delivery carries as seals. */
export const MAX_SEALS = 3;
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
    seals: 0,
  };
}

function push(lines: string[], line: string, keep: number): string[] {
  return [...lines, line].slice(-keep);
}

/**
 * Keep the result panel on a delivery that waits for the person: another
 * task's delivery never takes it away, and once it is decided the panel
 * moves to the next one waiting, if any.
 */
function refocus(state: RoomState): RoomState {
  const waits = (id?: string) => !!id && state.tasks[id]?.state === 'waiting_for_person' && !!state.tasks[id].delivery;
  if (waits(state.focus)) return state;
  const next = Object.values(state.tasks).find((t) => waits(t.id));
  return next ? { ...state, focus: next.id } : state;
}

/** Apply one event. Pure: returns a new state and leaves `state` untouched. */
export function reduce(state: RoomState, event: RoomEvent): RoomState {
  return refocus(apply(state, event));
}

function apply(state: RoomState, event: RoomEvent): RoomState {
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
        // A new delivery starts with no seals; each confirmation by the
        // Verifier adds one.
        active: event.type === 'agent_start' ? event.role : state.active,
        seals:
          event.type === 'agent_start' && event.role === 'Developer'
            ? 0
            : event.role === 'Verifier' && event.type !== 'agent_start' && event.type !== 'error'
              ? Math.min(MAX_SEALS, state.seals + 1)
              : state.seals,
        agents: {
          ...state.agents,
          [event.role]: { ...agent, state: agentState, lines: push(agent.lines, event.message, AGENT_LINES) },
        },
      };
    }
    case 'delivery': {
      // A delivery waiting for the person keeps the panel; others take it.
      const holds = state.focus !== undefined && state.focus !== task.id && state.tasks[state.focus]?.state === 'waiting_for_person';
      return {
        ...state,
        focus: holds ? state.focus : event.taskId,
        seals: Math.min(MAX_SEALS, event.delivery.checks.filter((c) => c.ok).length),
        tasks: { ...state.tasks, [task.id]: { ...task, delivery: event.delivery, decision: undefined } },
      };
    }
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

/** Where the task is in the room: with an agent, at the result, or nowhere. */
export function tokenAt(state: RoomState): Role | 'result' | 'none' {
  const active = state.active;
  if (active && state.agents[active].state === 'working') return active;
  const focused = state.focus ? state.tasks[state.focus] : undefined;
  if (focused?.delivery && (focused.state === 'waiting_for_person' || focused.state === 'done')) return 'result';
  const busy = Object.values(state.tasks).some((t) => ['in_progress', 'in_review', 'sent_back'].includes(t.state));
  return busy && active ? active : 'none';
}

/** A delivery waits for a person only when its task does. */
export function awaitingDecision(state: RoomState): TaskView | undefined {
  const focused = state.focus ? state.tasks[state.focus] : undefined;
  return focused?.state === 'waiting_for_person' ? focused : undefined;
}
