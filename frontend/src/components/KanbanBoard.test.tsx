import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import KanbanBoard from './KanbanBoard'
import { useSprintBoard, useUpdateBacklogItem } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'

// The board and the mutation are stubbed; the agent-run query is real so the
// test observes the HTTP requests the board makes for delivery verdicts.
vi.mock('../hooks/useQueries', async importOriginal => ({
  ...(await importOriginal<typeof import('../hooks/useQueries')>()),
  useSprintBoard: vi.fn(),
  useUpdateBacklogItem: vi.fn(),
}))

function makeItem(id: number, title: string, status = 'todo') {
  return {
    id, sprint_id: 7, title, description: '', status, priority: 'high',
    assignee: 'Developer', comments: [], created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
  }
}

const item = makeItem(2, 'Encrypt credentials')

function run(id: number, externalRef: string, version: number, status: string, producer = 'le-fabrique-task-worker') {
  return {
    id, company_id: 42, external_ref: externalRef, version, producer, model: null, agent_role: 'Developer',
    subject: { sprint_id: 7 }, claims: null, artifact_digest: 'd', artifact_size: 1, status,
    started_at: null, finished_at: null, ingested_at: '2026-10-01T00:00:00Z', audit_log_id: null, latest_approval: null,
  }
}

function stubRuns(runs: unknown[]) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ agent_runs: runs }),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderBoard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/sprints/7/board']}>
        <Routes>
          <Route path="/sprints/7/board" element={<KanbanBoard sprintId="7" />} />
          <Route path="/sprints/:sprintId/tasks/:taskId" element={<p>Task page</p>} />
          <Route path="/evidence/:runId" element={<p>Evidence page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Kanban cards', () => {
  const mutate = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ companyId: 42 })
    vi.mocked(useSprintBoard).mockReturnValue({
      data: { sprint: { id: 7, sprint_name: 'Hardening' }, columns: { todo: [item] }, total: 1 },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    vi.mocked(useUpdateBacklogItem).mockReturnValue({ mutate, isPending: false } as never)
    stubRuns([])
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('links the card title to the task page and keeps the status select', () => {
    renderBoard()
    const link = screen.getByRole('link', { name: 'Encrypt credentials' })
    expect(link).toHaveAttribute('href', '/sprints/7/tasks/2')

    const card = link.closest('.card') as HTMLElement
    const select = within(card).getByRole('combobox', { name: 'Change status' })
    fireEvent.change(select, { target: { value: 'done' } })
    expect(mutate).toHaveBeenCalledWith({ itemId: 2, data: { status: 'done' } })

    fireEvent.click(link)
    expect(screen.getByText('Task page')).toBeInTheDocument()
  })

  it('badges each card with its latest delivery verdict from one sprint-wide request', async () => {
    vi.mocked(useSprintBoard).mockReturnValue({
      data: {
        sprint: { id: 7, sprint_name: 'Hardening' },
        columns: {
          todo: [item, makeItem(5, 'Write docs')],
          in_review: [makeItem(4, 'Add audit view', 'in_review')],
          done: [makeItem(3, 'Rotate keys', 'done')],
        },
        total: 4,
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    const fetchMock = stubRuns([
      run(31, 'task-2', 2, 'verified'),
      run(30, 'task-3', 1, 'unverifiable'),
      run(29, 'task-4', 1, 'ingested'),
      run(28, 'task-2', 1, 'refuted'),
    ])

    renderBoard()

    const verified = await screen.findByRole('link', { name: 'Delivery: Verified' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost')
    expect(url.pathname).toBe('/v1/agent_runs')
    expect(url.searchParams.get('sprint_id')).toBe('7')
    expect(url.searchParams.get('company_id')).toBe('42')
    expect(url.searchParams.get('producer')).toBe('le-fabrique-task-worker')
    expect(url.searchParams.has('external_ref')).toBe(false)

    // Task 2's latest version (v2, verified) wins over the refuted v1.
    expect(verified).toHaveAttribute('href', '/evidence/31')
    const card = screen.getByRole('link', { name: 'Encrypt credentials' }).closest('.card') as HTMLElement
    expect(within(card).getByRole('link', { name: 'Delivery: Verified' })).toBe(verified)
    expect(within(card).getByRole('combobox', { name: 'Change status' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Delivery: Refuted' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Delivery: Unverifiable' })).toHaveAttribute('href', '/evidence/30')

    // Not yet verified, or no run at all: no badge.
    for (const title of ['Add audit view', 'Write docs']) {
      const otherCard = screen.getByRole('link', { name: title }).closest('.card') as HTMLElement
      expect(within(otherCard).queryByRole('link', { name: /^Delivery:/ })).not.toBeInTheDocument()
    }
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  })
})
