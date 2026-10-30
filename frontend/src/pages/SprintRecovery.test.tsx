import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dashboard from './Dashboard'
import { SprintWorkspace } from './SprintWorkspace'
import { AnalyticsDashboard } from '../components/AnalyticsDashboard'
import { api, ApiError } from '../services/api'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAgentStore } from '../store/agentStore'

function Analytics() {
  const sprintId = useAppStore(state => state.activeSprintId)
  return <AnalyticsDashboard sprintId={sprintId ?? 0} />
}

function renderSprintPage(path = '/sprints/999') {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/sprints/:id" element={<SprintWorkspace />} />
          <Route path="/sprints/:id/:tab" element={<SprintWorkspace />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('stale persisted sprint recovery', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ activeSprintId: 999, companyId: 42 })
    vi.spyOn(api, 'getSprintBoard').mockRejectedValue(new ApiError(404, 'missing'))
    vi.spyOn(api, 'getAnalyticsSummary').mockRejectedValue(new ApiError(404, 'missing'))
    vi.spyOn(api, 'getQuotas').mockResolvedValue([])
    vi.spyOn(api, 'health').mockResolvedValue({ status: 'healthy' } as never)
    vi.spyOn(api, 'capabilities').mockResolvedValue({ agent_graph: false, memory: false, github: false, auth_required: true })
    vi.spyOn(useAgentStore.getState(), 'connect').mockImplementation(() => {})
    vi.spyOn(useAgentStore.getState(), 'disconnect').mockImplementation(() => {})
  })
  afterEach(() => {
    queryClient.clear()
    vi.restoreAllMocks()
  })

  it('the sprint page clears a persisted missing sprint and offers the sprint list', async () => {
    renderSprintPage()
    await waitFor(() => expect(useAppStore.getState().activeSprintId).toBeNull())
    expect(JSON.parse(localStorage.getItem('fabrique-app-storage')!).state.activeSprintId).toBeNull()
    expect(await screen.findByRole('alert')).toHaveTextContent('Sprint #999 was not found.')
    expect(screen.getByRole('link', { name: 'Sprints' })).toHaveAttribute('href', '/sprints')
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    expect(api.getSprintBoard).toHaveBeenCalledTimes(1)
  })

  it('Analytics clears a persisted missing sprint and exits the error state', async () => {
    render(<QueryClientProvider client={queryClient}><MemoryRouter><Analytics /></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(useAppStore.getState().activeSprintId).toBeNull())
    expect(JSON.parse(localStorage.getItem('fabrique-app-storage')!).state.activeSprintId).toBeNull()
    expect(screen.getAllByText('No active sprint').length).toBeGreaterThan(0)
    expect(screen.queryByText('Failed to load analytics')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sprints' })).toHaveAttribute('href', '/sprints')
    expect(api.getSprintBoard).toHaveBeenCalledTimes(1)
  })

  it('links an existing sprint to its Live tab', async () => {
    vi.mocked(api.getSprintBoard).mockResolvedValue({
      sprint: { id: 999, company_id: 42, sprint_name: 'Sprint 999', status: 'active', scope_size: 'M' },
      columns: {}, total: 0,
    } as never)
    renderSprintPage()
    const tabs = await screen.findByRole('tablist', { name: 'Sprint views' })
    expect(within(tabs).getByRole('tab', { name: 'Live' })).toHaveAttribute('href', '/sprints/999/live')
    expect(within(tabs).getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
  })

  it.each([
    [false, false], [true, false], [false, true], [true, true],
  ])('the Overview leaves shell destinations to the navigation bar (graph %s, memory %s)', async (agent_graph, memory) => {
    useAppStore.setState({ activeSprintId: null })
    vi.mocked(api.capabilities).mockResolvedValue({ agent_graph, memory, github: false, auth_required: true })
    render(<QueryClientProvider client={queryClient}><MemoryRouter><Dashboard sprintId={null} /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('button', { name: 'Generate Plan' })).toBeInTheDocument()
    for (const name of ['Generate', 'Memory', 'Analytics', 'Review', 'New Factory', 'Kanban Board']) {
      expect(screen.queryByRole('link', { name: new RegExp(name) })).not.toBeInTheDocument()
    }
  })
})
