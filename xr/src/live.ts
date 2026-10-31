/**
 * Live mode: the room follows a real sprint on La Fabrique's backend.
 *
 * Off unless the build sets `VITE_FABRIQUE_API` (the backend's address). The
 * page then reads `?sprint=<id>` and, when the backend requires
 * authentication, `?ticket=<stream ticket>` from its own address: the
 * five-minute, sprint-scoped ticket `POST /v1/sprints/{id}/stream_ticket`
 * hands to a Viewer, made for exactly this, since EventSource cannot send
 * headers. Live mode only watches; decisions stay in the web app, where a
 * Manager signs in. The backend must list the page's origin in
 * `CORS_ORIGINS`.
 */

import type { Role, RoomEvent } from './model';

export interface LiveConfig {
  api: string;
  sprintId: string;
  ticket?: string;
}

/** The live configuration, or undefined for the demo. */
export function liveConfig(api: string | undefined, search: string): LiveConfig | undefined {
  if (!api) return undefined;
  const params = new URLSearchParams(search);
  const sprintId = params.get('sprint') ?? '';
  if (!/^\d+$/.test(sprintId)) return undefined;
  const ticket = params.get('ticket') ?? undefined;
  return { api: api.replace(/\/+$/, ''), sprintId, ticket };
}

export function streamUrl(cfg: LiveConfig): string {
  const q = new URLSearchParams({ sprint_id: cfg.sprintId });
  if (cfg.ticket) q.set('ticket', cfg.ticket);
  return `${cfg.api}/v1/glassroom/stream?${q}`;
}

const ROLE_OF: Record<string, Role> = {
  Architect: 'Architect',
  Developer: 'Developer',
  QA: 'QA',
  ScrumMaster: 'ScrumMaster',
};

/** The backend's gate authors (`services/board.py`) speak as the Verifier. */
const VERIFIER_AGENTS = new Set(['Verifier', 'Quality gate']);

function roleOf(agent: string, role: string): Role | 'System' {
  if (VERIFIER_AGENTS.has(agent)) return 'Verifier';
  return ROLE_OF[role] ?? 'System';
}

const TYPES = new Set(['agent_start', 'agent_complete', 'status', 'message', 'error']);

/**
 * Turn one Glassroom event into a room event for `taskId`, or undefined when
 * it is not one the room shows (a keepalive, an unknown type).
 */
export function toRoomEvent(raw: unknown, taskId: string): RoomEvent | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const e = raw as Record<string, unknown>;
  const type = String(e.type ?? '');
  if (!TYPES.has(type)) return undefined;
  const agent = String(e.agent ?? e.role ?? 'System');
  const message = String(e.message ?? e.content ?? '').trim();
  if (!message && type !== 'agent_start' && type !== 'agent_complete') return undefined;
  const role = roleOf(agent, String(e.role ?? ''));
  if (role === 'System') {
    // A System event never starts or finishes an agent: it goes to the log.
    return { type: type === 'error' ? 'error' : 'status', role, agent, message, taskId };
  }
  return { type, role, agent, message, taskId } as RoomEvent;
}

/** Follow the sprint's stream; returns a function that stops it. */
export function connectLive(
  cfg: LiveConfig,
  taskId: string,
  onEvent: (event: RoomEvent) => void,
  onStatus: (text: string) => void,
): () => void {
  const source = new EventSource(streamUrl(cfg));
  source.onopen = () => onStatus(`Live: sprint ${cfg.sprintId}`);
  source.onerror = () => onStatus('Live: reconnecting to the factory...');
  source.onmessage = (msg) => {
    let raw: unknown;
    try {
      raw = JSON.parse(msg.data);
    } catch {
      return;
    }
    const event = toRoomEvent(raw, taskId);
    if (event) onEvent(event);
  };
  return () => source.close();
}
