import { describe, expect, it } from 'vitest'
import { carryOverLineage } from './carryOver'

describe('carryOverLineage', () => {
  it('reads the earlier and later attempts from the backend comments', () => {
    const lineage = carryOverLineage([
      { author: 'System', text: 'Carried over from task 7 ("Sprint 0 — Foundations"), which was blocked: too short', created_at: '' },
      { author: 'Quality gate', text: 'NEEDS WORK: too short', created_at: '' },
      { author: 'System', text: 'Carried over to sprint 3 ("Sprint 2") as task 11 by ana@example.com.', created_at: '' },
    ])

    expect(lineage).toEqual({
      from: { taskId: 7, sprintName: 'Sprint 0 — Foundations' },
      to: { sprintId: 3, sprintName: 'Sprint 2', taskId: 11 },
    })
  })

  it('is empty for an ordinary task', () => {
    expect(carryOverLineage([{ author: 'Dev', text: 'Carried the box over.', created_at: '' }])).toEqual({ from: null, to: null })
    expect(carryOverLineage(undefined)).toEqual({ from: null, to: null })
  })
})
