import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LearningTrend } from './LearningTrend'
import { architectAdvice, consoleAdvice, learningTrend, secondAttempts } from '../lib/learningTrend'
import type { SprintSummary } from '../services/api'

const sprint = (overrides: Partial<SprintSummary>): SprintSummary => ({
  id: 1, sprint_name: 'S', status: 'completed', goal: null, start_date: null, scope_size: 'S',
  total: 4, done: 4, blocked: 0, rework: 0,
  second_attempts: { total: 0, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, ...overrides,
})

const SPRINTS: SprintSummary[] = [
  sprint({ id: 9, sprint_name: 'Hardening', status: 'active', total: 8, done: 3, blocked: 1, rework: 7 }),
  sprint({ id: 7, sprint_name: 'Sprint 2', total: 5, done: 4, blocked: 1, rework: 2 }),
  sprint({ id: 4, sprint_name: 'Sprint 1', total: 4, done: 2, blocked: 2, rework: 4 }),
  sprint({ id: 2, sprint_name: 'Empty', total: 0, done: 0 }),
]

describe('learningTrend', () => {
  it('reads closed sprints with tasks, oldest first, as rework per task and blocked share', () => {
    const points = learningTrend(SPRINTS)
    expect(points.map(p => p.name)).toEqual(['Sprint 1', 'Sprint 2'])
    expect(points[0]).toMatchObject({ reworkPerTask: 1, blockedShare: 0.5 })
    expect(points[1]).toMatchObject({ name: 'Sprint 2', reworkPerTask: 0.4, blockedShare: 0.2 })
  })

  it('has nothing to say before a sprint closes', () => {
    expect(learningTrend([SPRINTS[0]])).toEqual([])
  })
})

describe('LearningTrend', () => {
  it('shows the latest closed sprint, the change since the one before and every sprint in a table', () => {
    render(<LearningTrend sprints={SPRINTS} />)

    const section = screen.getByRole('region', { name: 'Is the company learning?' })
    // The latest values head the tiles and close the table.
    expect(within(section).getAllByText('0.40')).toHaveLength(2)
    expect(within(section).getAllByText('20%')).toHaveLength(2)
    // Lower is better: both dropped since Sprint 1.
    expect(within(section).getByText('−0.60')).toBeInTheDocument()
    expect(within(section).getByText('−30%')).toBeInTheDocument()
    expect(within(section).getAllByText('vs previous sprint')).toHaveLength(2)

    const [rework, blocked] = within(section).getAllByRole('img')
    expect(rework).toHaveAccessibleName('Rework requests per task')
    // Each column names its sprint and value on hover and focus.
    const titles = (chart: HTMLElement) => Array.from(chart.querySelectorAll('title')).map(node => node.textContent)
    expect(titles(rework)).toEqual(['Sprint 1: 1.00', 'Sprint 2: 0.40'])
    expect(titles(blocked)).toEqual(['Sprint 1: 50%', 'Sprint 2: 20%'])

    const table = within(section).getByRole('table', { name: 'Closed sprints, oldest first' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map(row => within(row).getByRole('rowheader').textContent)).toEqual(['Sprint 1', 'Sprint 2'])
    expect(rows[1]).toHaveTextContent('0.40')
    expect(rows[1]).toHaveTextContent('20%')
  })

  it('tallies second attempts over closed sprints, with and without the brief', () => {
    const sprints = [
      // Still open: its attempts have no outcome yet.
      sprint({ id: 9, status: 'active', second_attempts: { total: 2, done: 0, briefed: 2, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } }),
      sprint({ id: 7, sprint_name: 'Sprint 2', second_attempts: { total: 3, done: 2, briefed: 2, briefed_done: 2 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } }),
      sprint({ id: 4, sprint_name: 'Sprint 1', second_attempts: { total: 1, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } }),
    ]
    expect(secondAttempts(sprints)).toEqual({ total: 4, done: 2, briefed: 2, briefed_done: 2 })

    render(<LearningTrend sprints={sprints} />)
    const section = screen.getByRole('region', { name: 'Is the company learning?' })
    expect(within(section).getByText('Second attempts that got done')).toBeInTheDocument()
    expect(within(section).getByText('2 of 4')).toBeInTheDocument()
    expect(within(section).getByText("With the ScrumMaster's brief: 2 of 2 · without: 0 of 2")).toBeInTheDocument()
  })

  it('compares tasks that got console advice with the rest, over closed sprints', () => {
    const group = (total: number, done: number, rework: number) => ({ total, done, rework })
    const sprints = [
      // Still open: not counted.
      sprint({ id: 9, status: 'active', console_advice: { advised: group(5, 0, 0), unadvised: group(1, 0, 0) } }),
      sprint({ id: 7, sprint_name: 'Sprint 2', console_advice: { advised: group(2, 2, 1), unadvised: group(2, 1, 3) } }),
      sprint({ id: 4, sprint_name: 'Sprint 1', console_advice: { advised: group(2, 1, 1), unadvised: group(2, 1, 1) } }),
    ]
    expect(consoleAdvice(sprints)).toEqual({ advised: group(4, 3, 2), unadvised: group(4, 2, 4) })

    render(<LearningTrend sprints={sprints} />)
    const section = screen.getByRole('region', { name: 'Is the company learning?' })
    expect(within(section).getByText('Tasks done with console advice')).toBeInTheDocument()
    expect(within(section).getByText('3 of 4')).toBeInTheDocument()
    expect(within(section).getByText('0.50 rework requests per task · without advice: 2 of 4 done, 1.00 per task')).toBeInTheDocument()
  })

  it('leaves out console advice before any task got it', () => {
    render(<LearningTrend sprints={SPRINTS} />)
    expect(screen.queryByText('Tasks done with console advice')).not.toBeInTheDocument()
  })

  it("compares tasks the Architect briefed with the rest, over closed sprints", () => {
    const group = (total: number, done: number, rework: number) => ({ total, done, rework })
    const sprints = [
      // Still open: not counted.
      sprint({ id: 9, status: 'active', architect_advice: { advised: group(3, 0, 0), unadvised: group(1, 0, 0) } }),
      sprint({ id: 7, sprint_name: 'Sprint 2', architect_advice: { advised: group(1, 1, 0), unadvised: group(3, 3, 1) } }),
      sprint({ id: 4, sprint_name: 'Sprint 1', architect_advice: { advised: group(1, 0, 2), unadvised: group(3, 2, 1) } }),
    ]
    expect(architectAdvice(sprints)).toEqual({ advised: group(2, 1, 2), unadvised: group(6, 5, 2) })

    render(<LearningTrend sprints={sprints} />)
    const section = screen.getByRole('region', { name: 'Is the company learning?' })
    expect(within(section).getByText("Tasks done with the Architect's brief")).toBeInTheDocument()
    expect(within(section).getByText('1 of 2')).toBeInTheDocument()
    expect(within(section).getByText('1.00 rework requests per task after the brief · without one: 5 of 6 done, 0.33 per task')).toBeInTheDocument()
    // No console advice in these sprints: no card for it.
    expect(within(section).queryByText('Tasks done with console advice')).not.toBeInTheDocument()
  })

  it('leaves out the second attempts before any task was carried over', () => {
    render(<LearningTrend sprints={SPRINTS} />)
    expect(screen.queryByText('Second attempts that got done')).not.toBeInTheDocument()
  })

  it('shows one closed sprint without a comparison, and nothing when none closed', () => {
    const { rerender } = render(<LearningTrend sprints={[SPRINTS[0], SPRINTS[2]]} />)
    const section = screen.getByRole('region', { name: 'Is the company learning?' })
    expect(within(section).getAllByText('1.00')).toHaveLength(2)
    expect(within(section).queryByText('vs previous sprint')).not.toBeInTheDocument()
    expect(within(section).queryByRole('img')).not.toBeInTheDocument()

    rerender(<LearningTrend sprints={[SPRINTS[0], SPRINTS[3]]} />)
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })
})
