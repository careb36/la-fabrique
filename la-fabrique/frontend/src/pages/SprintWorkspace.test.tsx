import { useEffect } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SprintWorkspace } from './SprintWorkspace'
import { api, ApiError, type SprintBoard } from '../services/api'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { QUERY_KEYS } from '../hooks/useQueries'

const disconnect = vi.hoisted(() => vi.fn())

vi.mock('../components/GlassRoom', () => ({
  default: ({ sprintId }: { sprintId: string }) => {
    useEffect(() => () => { disconnect() }, [sprintId])
    return <div>Stream for sprint {sprintId}</div>
  },
}))
vi.mock('../components/KanbanBoard', () => ({
  default: ({ sprintId }: { sprintId: string }) => <div>Board for sprint {sprintId}</div>,
}))
vi.mock('../components/AnalyticsDashboard', () => ({
  AnalyticsDashboard: ({ sprintId }: { sprintId: number }) => <div>Analytics for sprint {sprintId}</div>,
}))
vi.mock('../components/Conversation', () => ({
  Conversation: ({ companyId, sprintId, live }: { companyId: number; sprintId: number; live: boolean }) => (
    <div>Conversation of company {companyId} for sprint {sprintId}{live ? ' (live)' : ''}</div>
  ),
}))
vi.mock('./Dashboard', () => ({
  default: ({ sprintId }: { sprintId: number }) => <div>Overview for sprint {sprintId}</div>,
}))

const board = { sprint: { id: 8, company_id: 1, sprint_name: 'Hardening', status: 'active' }, columns: {}, total: 0 } as SprintBoard

function setup(id: string, tab = 'live') {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[tab ? `/sprints/${id}/${tab}` : `/sprints/${id}`]}>
        <Routes>
          <Route path="/sprints/:id" element={<SprintWorkspace />} />
          <Route path="/sprints/:id/:tab" element={<SprintWorkspace />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('workspace sprint validation', () => {
  const defaultOptions = queryClient.getDefaultOptions()

  beforeEach(() => {
    queryClient.clear()
    disconnect.mockClear()
    useAppStore.setState({ companyId: 1, activeSprintId: 7 })
  })
  afterEach(() => {
    queryClient.clear()
    queryClient.setDefaultOptions(defaultOptions)
    vi.restoreAllMocks()
  })

  it('does not persist or stream a missing URL sprint, even with a different selection', async () => {
    vi.spyOn(api, 'getSprintBoard').mockRejectedValue(new ApiError(404, 'missing'))
    setup('999')
    expect(await screen.findByRole('alert')).toHaveTextContent('Sprint #999 was not found')
    expect(screen.getByRole('link', { name: 'Sprints' })).toHaveAttribute('href', '/sprints')
    expect(screen.queryByText(/Stream for sprint/)).not.toBeInTheDocument()
    expect(useAppStore.getState().activeSprintId).toBe(7)
    expect(JSON.parse(localStorage.getItem('fabrique-app-storage')!).state.activeSprintId).toBe(7)
    expect(api.getSprintBoard).toHaveBeenCalledWith(999)
  })

  it('waits for URL sprint validation before persisting or connecting', async () => {
    let resolve!: (board: SprintBoard) => void
    vi.spyOn(api, 'getSprintBoard').mockReturnValue(new Promise(resolvePromise => { resolve = resolvePromise }))
    setup('8')
    expect(useAppStore.getState().activeSprintId).toBe(7)
    expect(screen.queryByText(/Stream for sprint/)).not.toBeInTheDocument()
    await act(async () => { resolve(board) })
    await waitFor(() => expect(useAppStore.getState().activeSprintId).toBe(8))
    expect(screen.getByText('Stream for sprint 8')).toBeInTheDocument()
    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(breadcrumb).getAllByRole('listitem').map(item => item.textContent)).toEqual(['Sprints', 'Hardening'])
    expect(within(breadcrumb).getByRole('link', { name: 'Sprints' })).toHaveAttribute('href', '/sprints')
    expect(screen.queryByRole('link', { name: 'Sprint Board' })).not.toBeInTheDocument()
  })

  it('clears a forbidden selection and explains lost access without Retry', async () => {
    useAppStore.setState({ activeSprintId: 999 })
    vi.spyOn(api, 'getSprintBoard').mockRejectedValue(new ApiError(403, 'forbidden'))
    setup('999')
    expect(await screen.findByRole('alert')).toHaveTextContent('You no longer have access to sprint #999.')
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Stream for sprint/)).not.toBeInTheDocument()
    await waitFor(() => expect(useAppStore.getState().activeSprintId).toBeNull())
  })

  it.each([new ApiError(503, 'unavailable'), new TypeError('Failed to fetch')])(
    'keeps the live view mounted after a background refresh fails: %s',
    async error => {
      queryClient.setDefaultOptions({ queries: { ...defaultOptions.queries, retry: false } })
      const fetchBoard = vi.spyOn(api, 'getSprintBoard').mockResolvedValueOnce(board).mockRejectedValueOnce(error).mockResolvedValue(board)
      setup('8')
      const stream = await screen.findByText('Stream for sprint 8')
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: QUERY_KEYS.sprintBoard(8) })
      })
      const alert = await screen.findByRole('alert')
      expect(screen.getByText('Stream for sprint 8')).toBe(stream)
      expect(disconnect).not.toHaveBeenCalled()
      expect(alert).toHaveTextContent('Failed to refresh this sprint. Showing the last loaded view.')
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
      await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
      expect(fetchBoard).toHaveBeenCalledTimes(3)
      expect(screen.getByText('Stream for sprint 8')).toBe(stream)
      expect(disconnect).not.toHaveBeenCalled()
    },
  )

  it.each([
    { status: 403, message: 'You no longer have access to sprint #8.' },
    { status: 404, message: 'Sprint #8 was not found.' },
  ])('does not offer Retry for a cached board returning HTTP $status', async ({ status, message }) => {
    vi.spyOn(api, 'getSprintBoard').mockResolvedValueOnce(board).mockRejectedValue(new ApiError(status, 'inaccessible'))
    setup('8')
    await screen.findByText('Stream for sprint 8')
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: QUERY_KEYS.sprintBoard(8) })
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(useAppStore.getState().activeSprintId).toBeNull()
  })

  it('offers Retry when the initial load fails without cached data', async () => {
    queryClient.setDefaultOptions({ queries: { ...defaultOptions.queries, retry: false } })
    vi.spyOn(api, 'getSprintBoard').mockRejectedValueOnce(new ApiError(503, 'unavailable')).mockResolvedValue(board)
    setup('8')
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load sprint #8.')
    expect(screen.queryByText(/Stream for sprint/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Stream for sprint 8')).toBeInTheDocument()
  })

  it.each([2, null])('does not select a URL sprint from another company when companyId is %s', async companyId => {
    useAppStore.setState({ companyId, companyName: 'Selected company' })
    const previousState = useAppStore.getState()
    const persisted = localStorage.getItem('fabrique-app-storage')
    const setActiveSprint = vi.spyOn(previousState, 'setActiveSprint')
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8')
    expect(await screen.findByText('Stream for sprint 8')).toBeInTheDocument()
    expect(setActiveSprint).not.toHaveBeenCalled()
    expect(useAppStore.getState()).toEqual(previousState)
    expect(localStorage.getItem('fabrique-app-storage')).toBe(persisted)
    expect(screen.getByRole('alert')).toHaveTextContent('This sprint belongs to another company. This view is read-only.')
    expect(screen.getByRole('link', { name: 'Select company' })).toHaveAttribute('href', '/companies/select')
  })

  it.each(['nope', '8junk', '0', '-1', '1.5', '9007199254740992'])('rejects malformed sprint ID %s without a request', id => {
    const fetchBoard = vi.spyOn(api, 'getSprintBoard')
    setup(id)
    expect(screen.getByRole('alert')).toHaveTextContent(`Invalid sprint ID: ${id}`)
    expect(fetchBoard).not.toHaveBeenCalled()
    expect(useAppStore.getState().activeSprintId).toBe(7)
  })

  it.each([
    ['', 'Overview', 'Overview for sprint 8'],
    ['board', 'Board', 'Board for sprint 8'],
    ['live', 'Live', 'Stream for sprint 8'],
    ['conversation', 'Conversation', /Conversation of company \d+ for sprint 8/],
    ['analytics', 'Analytics', 'Analytics for sprint 8'],
    ['ANALYTICS', 'Analytics', 'Analytics for sprint 8'],
  ] as [string, string, string | RegExp][])('selects the %s tab from the URL', async (tab, label, content) => {
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8', tab)
    expect(await screen.findByText(content)).toBeInTheDocument()
    const tabs = screen.getByRole('tablist', { name: 'Sprint views' })
    expect(within(tabs).getAllByRole('tab').map(item => item.textContent)).toEqual(['Overview', 'Board', 'Live', 'Conversation', 'Analytics'])
    const selected = within(tabs).getAllByRole('tab').filter(item => item.getAttribute('aria-selected') === 'true')
    expect(selected).toHaveLength(1)
    expect(selected[0]).toHaveTextContent(label)
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', selected[0].id)
    expect(within(tabs).getByRole('tab', { name: 'Board' })).toHaveAttribute('href', '/sprints/8/board')
    expect(within(tabs).getByRole('tab', { name: 'Overview' })).toHaveAttribute('href', '/sprints/8')
  })

  it.each(['bogus', 'overview', 'tasks'])('falls back to Overview for the unknown tab %s', async tab => {
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8', tab)
    expect(await screen.findByText('Overview for sprint 8')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
  })

  it('offers Pause and Resume on the Board tab only', async () => {
    const pause = vi.spyOn(api, 'pauseSprint').mockResolvedValue({} as never)
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8', 'board')
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }))
    await waitFor(() => expect(pause).toHaveBeenCalledWith(8))
    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }))
    expect(await screen.findByText('Overview for sprint 8')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
  })

  it('dispatches the pending tasks and reports how many went out', async () => {
    const dispatch = vi.spyOn(api, 'dispatchSprint').mockResolvedValue({ dispatched: 3, sprint_id: 8 })
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8', 'board')
    fireEvent.click(await screen.findByRole('button', { name: 'Dispatch pending' }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith(8))
  })

  it('shows a failed sprint action with its reason and retries it', async () => {
    const dispatch = vi.spyOn(api, 'dispatchSprint')
      .mockRejectedValueOnce(new ApiError(403, 'Forbidden', 'Requires Manager role'))
      .mockResolvedValueOnce({ dispatched: 0, message: 'No todo items to dispatch' })
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue(board)
    setup('8', 'board')
    fireEvent.click(await screen.findByRole('button', { name: 'Dispatch pending' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Requires Manager role')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('does not dispatch a paused sprint', async () => {
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue({ ...board, sprint: { ...board.sprint, status: 'paused' } })
    setup('8', 'board')
    expect(await screen.findByRole('button', { name: 'Dispatch pending' })).toBeDisabled()
  })

  it('offers Resume for a paused sprint', async () => {
    const resume = vi.spyOn(api, 'resumeSprint').mockResolvedValue({} as never)
    vi.spyOn(api, 'getSprintBoard').mockResolvedValue({ ...board, sprint: { ...board.sprint, status: 'paused' } })
    setup('8', 'board')
    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await waitFor(() => expect(resume).toHaveBeenCalledWith(8))
  })
})
