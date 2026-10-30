import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Procedures from './Procedures'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const BASE = {
  supersedes_id: null, source_sprint_id: 3, created_at: null, decided_at: null, retired_at: null,
}
const PROCEDURES = [
  {
    ...BASE, id: 3, role: 'Developer', title: 'Validate inputs', body: 'Validate every input.', status: 'proposed',
    version: 1, proposed_by: 'ScrumMaster', rationale: 'two tasks came back', baseline: null, outcome: null, decided_by: null,
  },
  {
    ...BASE, id: 2, role: 'All', title: 'Small tasks', body: 'Split big work.', status: 'active', version: 2,
    proposed_by: 'ScrumMaster', rationale: null, decided_by: 'autonomy',
    baseline: { sprints: 2, tasks: 8, rework_per_task: 0.5, blocked_rate: 0.25 }, outcome: null,
  },
  {
    ...BASE, id: 1, role: 'QA', title: 'Strict review', body: 'Reject anything untested.', status: 'retired', version: 1,
    proposed_by: 'ana@acme.test', rationale: null, decided_by: 'ana@acme.test',
    baseline: { sprints: 2, tasks: 6, rework_per_task: 0.2, blocked_rate: 0 },
    outcome: { sprints: 2, tasks: 6, rework_per_task: 1, blocked_rate: 0.5, result: 'reverted' },
  },
]

function stubApi(overrides: Record<string, () => Response> = {}) {
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const { pathname } = new URL(url)
    const key = `${init.method ?? 'GET'} ${pathname}`
    if (overrides[key]) return overrides[key]()
    if (key === 'GET /v1/procedures') return response(200, { procedures: PROCEDURES })
    if (key === 'GET /v1/agents') return response(200, { agents: [{ id: 1, role: 'Developer' }, { id: 2, role: 'QA' }] })
    return response(404)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderAs(role: 'Owner' | 'Manager' | 'Viewer') {
  useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000, memberships: [{ company_id: 4, human_role: role }] })
  return render(
    <QueryClientProvider client={queryClient}>
      <Procedures />
    </QueryClientProvider>,
  )
}

describe('Procedures', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('groups proposals, procedures in force and history with their numbers', async () => {
    stubApi()
    renderAs('Viewer')

    const proposed = await screen.findByRole('region', { name: 'Waiting for a decision' })
    expect(proposed).toHaveTextContent('Validate inputs')
    expect(proposed).toHaveTextContent('Why: two tasks came back')
    expect(within(proposed).queryByRole('button', { name: 'Adopt' })).not.toBeInTheDocument()

    const active = screen.getByRole('region', { name: 'In force' })
    expect(active).toHaveTextContent('Every role')
    expect(active).toHaveTextContent('v2')
    expect(active).toHaveTextContent('Before: 0.5 rework requests per task, 25% blocked (2 sprints).')
    expect(active).toHaveTextContent('Measured after the next two completed sprints.')

    const history = screen.getByRole('region', { name: 'History' })
    expect(history).toHaveTextContent('Reverted')
    expect(history).toHaveTextContent('After: 1 per task, 50% blocked (2 sprints).')
    expect(screen.queryByRole('region', { name: 'Write a procedure' })).not.toBeInTheDocument()
  })

  it('lets a manager adopt a proposal and write a procedure', async () => {
    const fetch = stubApi({
      'POST /v1/procedures/3/adopt': () => response(200, { ...PROCEDURES[0], status: 'active' }),
      'POST /v1/procedures': () => response(201, { ...PROCEDURES[1], id: 9 }),
    })
    renderAs('Manager')

    const proposed = await screen.findByRole('region', { name: 'Waiting for a decision' })
    fireEvent.click(within(proposed).getByRole('button', { name: 'Adopt' }))
    await waitFor(() => expect(fetch.mock.calls.some(([url, init]) => url.endsWith('/v1/procedures/3/adopt') && init?.method === 'POST')).toBe(true))

    const form = screen.getByRole('region', { name: 'Write a procedure' })
    await waitFor(() => expect(within(form).getByRole('option', { name: 'QA' })).toBeInTheDocument())
    fireEvent.change(within(form).getByRole('combobox', { name: 'Role' }), { target: { value: 'QA' } })
    fireEvent.change(within(form).getByRole('textbox', { name: 'Title' }), { target: { value: ' Run the tests ' } })
    fireEvent.change(within(form).getByRole('textbox', { name: 'The rule' }), { target: { value: 'Always run them.' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Put in force' }))

    await waitFor(() => expect(within(form).getByRole('textbox', { name: 'Title' })).toHaveValue(''))
    const create = fetch.mock.calls.find(([url, init]) => new URL(url).pathname === '/v1/procedures' && init?.method === 'POST')!
    expect(JSON.parse(String(create[1]!.body))).toEqual({ company_id: 4, role: 'QA', title: 'Run the tests', body: 'Always run them.' })
  })

  it('offers a retry when loading fails', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(403, { detail: 'Not a member of this company' }))
      .mockResolvedValue(response(200, { procedures: [] }))
    vi.stubGlobal('fetch', fetch)
    renderAs('Viewer')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the procedures: Not a member of this company')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('No procedures in force yet.')).toBeInTheDocument()
  })
})
