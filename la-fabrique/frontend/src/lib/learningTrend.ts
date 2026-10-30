/**
 * The numbers that say whether the company is learning, per closed sprint.
 *
 * Rework requests per task and the share of blocked tasks are what keeps or
 * reverts a procedure (backend `services/procedures.py`); shown sprint by
 * sprint, oldest to newest, they are the trend a person reads without opening
 * anything. Only completed sprints with at least one task count: an active
 * sprint's numbers are still moving and an empty one measures nothing.
 */
import type { AdviceGroup, ConsoleAdvice, SecondAttempts, SprintSummary } from '../services/api'

export interface SprintPoint {
  id: number
  name: string
  reworkPerTask: number
  blockedShare: number
}

const closed = (sprint: SprintSummary) => sprint.status === 'completed' && sprint.total > 0

/** Closed sprints with tasks, oldest first. Empty when nothing closed yet. */
export function learningTrend(sprints: SprintSummary[]): SprintPoint[] {
  return sprints
    .filter(closed)
    .sort((a, b) => a.id - b.id)
    .map(sprint => ({
      id: sprint.id,
      name: sprint.sprint_name,
      reworkPerTask: sprint.rework / sprint.total,
      blockedShare: sprint.blocked / sprint.total,
    }))
}

/**
 * Second attempts across the closed sprints: whether carrying a blocked task
 * over pays off, and whether the ScrumMaster's brief helps. Only closed
 * sprints count, so every attempt here has its outcome.
 */
export function secondAttempts(sprints: SprintSummary[]): SecondAttempts {
  const sum: SecondAttempts = { total: 0, done: 0, briefed: 0, briefed_done: 0 }
  for (const sprint of sprints.filter(closed)) {
    const tally = sprint.second_attempts
    if (!tally) continue
    sum.total += tally.total
    sum.done += tally.done
    sum.briefed += tally.briefed
    sum.briefed_done += tally.briefed_done
  }
  return sum
}

/**
 * Advice across the closed sprints: tasks that got it and tasks that did
 * not, each with how many got done and how many rework requests they drew.
 * The advice is a claim; this is what the boards say.
 */
function adviceTally(sprints: SprintSummary[], pick: (sprint: SprintSummary) => ConsoleAdvice | undefined): ConsoleAdvice {
  const add = (sum: AdviceGroup, group?: AdviceGroup) => {
    if (!group) return
    sum.total += group.total
    sum.done += group.done
    sum.rework += group.rework
  }
  const tally: ConsoleAdvice = { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }
  for (const sprint of sprints.filter(closed)) {
    add(tally.advised, pick(sprint)?.advised)
    add(tally.unadvised, pick(sprint)?.unadvised)
  }
  return tally
}

/** Tasks a console assistant advised on against the rest. */
export const consoleAdvice = (sprints: SprintSummary[]) => adviceTally(sprints, sprint => sprint.console_advice)

/** Tasks the Architect briefed against the rest. */
export const architectAdvice = (sprints: SprintSummary[]) => adviceTally(sprints, sprint => sprint.architect_advice)

/** Rework requests per task in a group; 0 for an empty group. */
export const reworkPerTask = (group: AdviceGroup) => (group.total > 0 ? group.rework / group.total : 0)

export const formatRework = (value: number) => value.toFixed(2)
export const formatShare = (value: number) => `${Math.round(value * 100)}%`
