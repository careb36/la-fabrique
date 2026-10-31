/**
 * The company learns, across sessions, the way La Fabrique does: each run of
 * the demo is a sprint; when it closes, every rework it needed (QA's
 * NEEDS WORK, a person's send back) becomes a procedure the ScrumMaster
 * adopts, and the next sprint runs with it. Whether a procedure helped is
 * counted from the sprints' own events, never judged by a model.
 *
 * Pure: events and tasks in, the company's record out. The room keeps the
 * record on the device.
 */

import type { DemoTask } from './demo/scenario';
import type { RoomEvent } from './model';

export interface SprintRecord {
  sprint: number;
  tasks: number;
  /** Rework requests: QA's NEEDS WORK and a person's send backs. */
  rework: number;
}

export interface Procedure {
  /** The task whose rework taught it. */
  taskId: string;
  text: string;
  /** Who asked for the rework that taught it. */
  from: 'QA' | 'you';
  /** The sprint after which it was adopted. */
  adoptedAfter: number;
}

export interface Company {
  sprints: SprintRecord[];
  procedures: Procedure[];
}

export const NEW_COMPANY: Company = { sprints: [], procedures: [] };

/** Which tasks needed rework in a sprint, and who asked for it. */
export function reworkIn(history: readonly RoomEvent[]): Map<string, 'QA' | 'you'> {
  const asked = new Map<string, 'QA' | 'you'>();
  for (const e of history) {
    if (e.type === 'decision' && !e.approved) asked.set(e.taskId, 'you');
    else if ('message' in e && e.role === 'QA' && e.message.startsWith('NEEDS WORK') && !asked.has(e.taskId)) {
      asked.set(e.taskId, 'QA');
    }
  }
  return asked;
}

/** How many rework requests a sprint had. */
export function reworkCount(history: readonly RoomEvent[]): number {
  return history.filter(
    (e) => (e.type === 'decision' && !e.approved) || ('message' in e && e.role === 'QA' && e.message.startsWith('NEEDS WORK')),
  ).length;
}

/**
 * Close a sprint: record its numbers, and adopt a procedure for each task
 * that needed rework and has a lesson, unless one is already in force.
 */
export function closeSprint(company: Company, history: readonly RoomEvent[], tasks: DemoTask[]): Company {
  const sprint = company.sprints.length + 1;
  const record: SprintRecord = { sprint, tasks: tasks.length, rework: reworkCount(history) };
  const adopted = [...company.procedures];
  for (const [taskId, from] of reworkIn(history)) {
    const lesson = tasks.find((t) => t.id === taskId)?.learns;
    if (lesson && !adopted.some((p) => p.taskId === taskId)) {
      adopted.push({ taskId, text: lesson.procedure, from, adoptedAfter: sprint });
    }
  }
  return { sprints: [...company.sprints, record], procedures: adopted };
}

/** The tasks as the next sprint runs them: with every procedure in force. */
export function tasksWith(company: Company, tasks: DemoTask[]): DemoTask[] {
  return tasks.map((t) =>
    t.learns && company.procedures.some((p) => p.taskId === t.id) ? { ...t, script: t.learns.script } : t,
  );
}

/** Rework per task, sprint by sprint: the curve the company is judged by. */
export function curve(company: Company): number[] {
  return company.sprints.map((s) => (s.tasks ? s.rework / s.tasks : 0));
}

/** Read a stored company, tolerating anything malformed as a new one. */
export function parseCompany(raw: string | null): Company {
  if (!raw) return NEW_COMPANY;
  try {
    const c = JSON.parse(raw) as Company;
    if (!Array.isArray(c.sprints) || !Array.isArray(c.procedures)) return NEW_COMPANY;
    const sprints = c.sprints.filter(
      (s) => Number.isFinite(s?.sprint) && Number.isFinite(s?.tasks) && Number.isFinite(s?.rework),
    );
    const procedures = c.procedures.filter(
      (p) => typeof p?.taskId === 'string' && typeof p?.text === 'string' && (p.from === 'QA' || p.from === 'you'),
    );
    return { sprints, procedures };
  } catch {
    return NEW_COMPANY;
  }
}
