import type { BacklogItem } from '../services/api'

/**
 * What a task's comments say about its carry-over lineage, written by the
 * backend (`services/carry_over.py`) in a fixed form:
 *   "Carried over from task 7 ("Sprint 0"), which was blocked: …"
 *   "Carried over to sprint 3 ("Sprint 1") as task 9 by ana."
 */
export interface CarryOverLineage {
  /** The earlier attempt this task is a retry of. */
  from: { taskId: number; sprintName: string } | null
  /** The later attempt this (blocked) task was given. */
  to: { sprintId: number; sprintName: string; taskId: number } | null
}

const FROM = /^Carried over from task (\d+) \("(.*?)"\)/
const TO = /^Carried over to sprint (\d+) \("(.*?)"\) as task (\d+)/

export function carryOverLineage(comments: BacklogItem['comments'] | undefined): CarryOverLineage {
  const lineage: CarryOverLineage = { from: null, to: null }
  for (const comment of comments ?? []) {
    const text = comment.text ?? ''
    const from = FROM.exec(text)
    if (from) lineage.from = { taskId: Number(from[1]), sprintName: from[2] }
    const to = TO.exec(text)
    if (to) lineage.to = { sprintId: Number(to[1]), sprintName: to[2], taskId: Number(to[3]) }
  }
  return lineage
}
