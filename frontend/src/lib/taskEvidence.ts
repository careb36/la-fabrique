import type { AgentRun, AgentRunListItem } from '../services/api'

/** The producer the task worker records deliverables under (backend TASK_WORKER_PRODUCER). */
export const TASK_WORKER_PRODUCER = 'le-fabrique-task-worker'

/** Every version of a task's deliverable shares this external_ref. */
export function taskExternalRef(taskId: number): string {
  return `task-${taskId}`
}

function taskIdFromExternalRef(externalRef: string): number | null {
  const match = /^task-(\d+)$/.exec(externalRef)
  return match ? Number(match[1]) : null
}

/** item id → the highest-version task-worker run recorded for it. */
export function latestRunsByTask(runs: AgentRunListItem[]): Map<number, AgentRunListItem> {
  const latest = new Map<number, AgentRunListItem>()
  for (const run of runs) {
    if (run.producer !== TASK_WORKER_PRODUCER) continue
    const taskId = taskIdFromExternalRef(run.external_ref)
    if (taskId === null) continue
    const current = latest.get(taskId)
    if (!current || run.version > current.version) latest.set(taskId, run)
  }
  return latest
}

/** The task page a task-worker run delivered, or null when the run is not one. */
export function taskOfRun(run: Pick<AgentRun, 'producer' | 'subject'>): { to: string; itemId: number; title: string | null } | null {
  if (run.producer !== TASK_WORKER_PRODUCER || !run.subject) return null
  const { sprint_id: sprintId, backlog_item_id: itemId, title } = run.subject
  const isId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0
  if (!isId(sprintId) || !isId(itemId)) return null
  return {
    to: `/sprints/${sprintId}/tasks/${itemId}`,
    itemId,
    title: typeof title === 'string' && title.trim() ? title : null,
  }
}
