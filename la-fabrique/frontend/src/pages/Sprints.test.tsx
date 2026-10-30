import { render, screen, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Sprints from './Sprints'
import { api, type SprintSummary } from '../services/api'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'

const sprints: SprintSummary[] = [
  { id: 12, sprint_name: 'Docs polish', status: 'completed', goal: null, start_date: '2026-10-10', scope_size: 'S', total: 4, done: 4, blocked: 0, rework: 0, second_attempts: { total: 0, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } },
  { id: 9, sprint_name: 'Hardening', status: 'active', goal: 'Close audit gaps', start_date: '2026-10-01', scope_size: 'M', total: 8, done: 3, blocked: 1, rework: 2, second_attempts: { total: 0, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } },
  { id: 4, sprint_name: 'Foundation', status: 'needs_split', goal: null, start_date: null, scope_size: 'L', total: 0, done: 0, blocked: 0, rework: 0, second_attempts: { total: 0, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } },
]

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/sprints']}><Sprints /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Sprints list', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 42, companyName: 'Example', activeSprintId: 9 })
  })
  afterEach(() => {
    queryClient.clear()
    vi.restoreAllMocks()
  })

  it('renders each sprint with status, progress and start date, active first, linking to its page', async () => {
    const list = vi.spyOn(api, 'listSprints').mockResolvedValue(sprints)
    renderPage()
    const table = await screen.findByRole('list', { name: 'Sprints' })
    const rows = within(table).getAllByRole('listitem')
    expect(rows.map(row => within(row).getByRole('link').textContent)).toEqual(['Hardening', 'Docs polish', 'Foundation'])
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '/sprints/9')
    expect(within(rows[1]).getByRole('link')).toHaveAttribute('href', '/sprints/12')
    expect(within(rows[2]).getByRole('link')).toHaveAttribute('href', '/sprints/4')
    expect(rows[0]).toHaveTextContent('Active')
    expect(rows[0]).toHaveTextContent('3 / 8 done')
    expect(rows[0]).toHaveTextContent('38%')
    expect(rows[0]).toHaveTextContent('1 blocked · 2 rework requests')
    expect(rows[1]).not.toHaveTextContent('blocked')
    expect(rows[0]).toHaveTextContent('2026-10-01')
    expect(rows[0]).toHaveTextContent('Last opened')
    expect(rows[1]).toHaveTextContent('Completed')
    expect(rows[1]).toHaveTextContent('4 / 4 done')
    expect(rows[2]).toHaveTextContent('Needs Split')
    expect(rows[2]).toHaveTextContent('Not started')
    expect(list).toHaveBeenCalledWith(42)
  })

  it('offers a new company and sprint planning when the company has no sprints', async () => {
    vi.spyOn(api, 'listSprints').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText('No sprints yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New company' })).toHaveAttribute('href', '/companies/new')
    expect(screen.getByRole('link', { name: 'Plan a sprint' })).toHaveAttribute('href', '#plan-sprint')
    const planner = screen.getByRole('region', { name: 'Plan a sprint' })
    expect(planner).toHaveAttribute('id', 'plan-sprint')
    expect(within(planner).getByRole('button', { name: 'Generate Plan' })).toBeInTheDocument()
  })

  it('asks for a company instead of listing when none is selected', () => {
    const list = vi.spyOn(api, 'listSprints')
    useAppStore.setState({ companyId: null })
    renderPage()
    expect(screen.getByText('Select a company to see its sprints.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Select company' })).toHaveAttribute('href', '/companies/select')
    expect(list).not.toHaveBeenCalled()
  })
})
