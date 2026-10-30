import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest'
import HelpDesk from './HelpDesk'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const TICKET = {
  id: 1, ticket_num: 'BUG-0001', title: 'Board does not load', severity: 'high', category: null,
  status: 'open', reporter_email: 'ana@acme.test', assigned_to: null,
  created_at: '2026-10-01T10:00:00', updated_at: null, resolved_at: null,
}

const NO_RECORD = {
  severity: { decided: 0, agent_agreed: 0, agent_unusable: 0, reporter_chose: 0, reporter_agreed: 0 },
  category: { decided: 0, agent_agreed: 0, agent_unusable: 0, reporter_chose: 0, reporter_agreed: 0 },
}

function stubApi(overrides: Record<string, (init: RequestInit) => Response> = {}) {
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const { pathname } = new URL(url)
    const key = `${init.method ?? 'GET'} ${pathname}`
    if (overrides[key]) return overrides[key](init)
    if (key === 'GET /v1/support/tickets') return response(200, { tickets: [TICKET], count: 1 })
    if (key === 'GET /v1/support/agent_record') return response(200, NO_RECORD)
    if (key === 'GET /v1/support/tickets/BUG-0001') {
      return response(200, { ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null })
    }
    return response(404)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderAs(supportAdmin: boolean) {
  useAuthStore.setState({
    token: 'valid-token',
    expiresAt: Date.now() + 60_000,
    user: { user_id: 1, email: 'admin@acme.test', full_name: 'Admin', support_admin: supportAdmin },
    // Company roles do not matter: an Owner who is not a support admin is turned away.
    memberships: [{ company_id: 4, human_role: 'Owner' }],
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <HelpDesk />
    </QueryClientProvider>,
  )
}

describe('HelpDesk', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('is offered to support admins only', () => {
    const fetch = stubApi()
    renderAs(false)
    expect(screen.getByRole('status')).toHaveTextContent('The help desk is for support admins.')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('filters the ticket list with the parameters the API reads', async () => {
    const fetch = stubApi()
    renderAs(true)
    expect(await screen.findByText('Board does not load')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), { target: { value: 'waiting' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Impact' }), { target: { value: 'critical' } })
    const email = screen.getByRole('textbox', { name: 'Reporter email' })
    fireEvent.change(email, { target: { value: 'ana@acme.test' } })
    fireEvent.blur(email)

    await waitFor(() => {
      const url = new URL(fetch.mock.calls.at(-1)![0])
      expect(url.pathname).toBe('/v1/support/tickets')
      expect(Object.fromEntries(url.searchParams)).toEqual({ status: 'waiting', severity: 'critical', reporter_email: 'ana@acme.test' })
    })
  })

  it('requires a resolution to close a ticket, then saves it', async () => {
    const patch = vi.fn((init: RequestInit) => {
      void init
      return response(200, { ticket_num: 'BUG-0001', status: 'resolved', updated_at: '2026-10-02T00:00:00' })
    })
    stubApi({ 'PATCH /v1/support/tickets/BUG-0001': patch })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))

    const detail = await screen.findByRole('region', { name: 'Board does not load' })
    expect(within(detail).getByText('Spinner forever')).toBeInTheDocument()
    const status = within(detail).getByRole('combobox', { name: 'Status' })
    fireEvent.change(status, { target: { value: 'resolved' } })
    expect(within(detail).getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(within(detail).getByText(/Write the resolution/)).toBeInTheDocument()

    fireEvent.change(within(detail).getByRole('textbox', { name: 'Resolution' }), { target: { value: 'Fixed in 1.2' } })
    fireEvent.change(within(detail).getByRole('textbox', { name: 'Assigned to' }), { target: { value: 'sam' } })
    fireEvent.click(within(detail).getByRole('button', { name: 'Save' }))

    expect(await within(detail).findByText('Ticket updated')).toBeInTheDocument()
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({ status: 'resolved', resolution: 'Fixed in 1.2', assigned_to: 'sam' })
  })

  it('downloads the logs, and says so when none exist yet', async () => {
    const blob = new Blob(['{}\n'])
    const logs = vi.fn()
      .mockReturnValueOnce(response(404, { detail: 'Log file not found.' }))
      .mockReturnValueOnce({ ok: true, status: 200, headers: new Headers({ 'Content-Disposition': 'attachment; filename="audit.jsonl"' }), blob: async () => blob } as unknown as Response)
    stubApi({ 'GET /v1/support/logs': logs })
    const createObjectURL = vi.fn(() => 'blob:logs')
    const revokeObjectURL = vi.fn()
    // jsdom has no object URLs; set them for this test and restore them after.
    const original = { createObjectURL: URL.createObjectURL, revokeObjectURL: URL.revokeObjectURL }
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    onTestFinished(() => { Object.assign(URL, original) })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    onTestFinished(() => click.mockRestore())
    renderAs(true)

    fireEvent.click(screen.getByRole('button', { name: 'Download logs' }))
    expect(await screen.findByText('No logs have been written yet.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Download logs' }))
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect((click.mock.instances[0] as unknown as HTMLAnchorElement).download).toBe('audit.jsonl')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:logs')
    expect(screen.queryByText('No logs have been written yet.')).not.toBeInTheDocument()
  })
})

describe('HelpDesk triage by the Support agent', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it("shows the agent's suggestions beside the reporter's choice, and its reply", async () => {
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, {
        ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
        severity: 'low', triaged_by: 'Support agent', suggested_severity: 'high', suggested_category: 'bug',
        agent_reply: 'Thanks, we are looking into it.',
      }),
    })
    useAuthStore.setState({
      token: 'valid-token', expiresAt: Date.now() + 60_000,
      user: { user_id: 1, email: 'admin@acme.test', full_name: 'Admin', support_admin: true }, memberships: [],
    })
    render(<QueryClientProvider client={queryClient}><HelpDesk /></QueryClientProvider>)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))

    const triage = await screen.findByLabelText('Triage')
    expect(triage).toHaveTextContent('Triage by Support agent')
    expect(triage).toHaveTextContent('Suggested impact: High (reported: Low) · category: bug')
    expect(triage).toHaveTextContent('Thanks, we are looking into it.')
  })
})

describe('HelpDesk decisions on the agent\'s suggestions', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('decides impact and category apart from the suggestion, and shows the decision', async () => {
    const patch = vi.fn((init: RequestInit) => {
      void init
      return response(200, { ticket_num: 'BUG-0001', status: 'in_progress', updated_at: '2026-10-02T00:00:00' })
    })
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, {
        ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
        severity: 'low', triaged_by: 'Support agent', suggested_severity: 'high', suggested_category: 'bug',
        decided_severity: 'critical', decided_category: null, decided_by: 'admin@acme.test',
      }),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))

    const detail = await screen.findByRole('region', { name: 'Board does not load' })
    expect(within(detail).getByText('Decided: impact Critical · category —, last changed by admin@acme.test')).toBeInTheDocument()
    // The form starts from the earlier decision, not from the reporter's or the agent's value.
    expect(within(detail).getByRole('combobox', { name: 'Decided impact' })).toHaveValue('critical')
    expect(within(detail).getByRole('combobox', { name: 'Decided category' })).toHaveValue('')

    fireEvent.change(within(detail).getByRole('combobox', { name: 'Status' }), { target: { value: 'in_progress' } })
    fireEvent.change(within(detail).getByRole('combobox', { name: 'Decided category' }), { target: { value: 'incident' } })
    fireEvent.click(within(detail).getByRole('button', { name: 'Save' }))

    expect(await within(detail).findByText('Ticket updated')).toBeInTheDocument()
    // The unchanged impact is not sent again: saving is not deciding it anew.
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({
      status: 'in_progress', category: 'incident',
    })
  })

  it('clears a decision by sending it empty, and sends none when only the status changes', async () => {
    let detail: Record<string, unknown> = {
      ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
      decided_severity: 'critical', decided_category: 'bug', decided_by: 'admin@acme.test',
    }
    const patch = vi.fn((init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      detail = { ...detail, status: body.status }
      return response(200, { ticket_num: 'BUG-0001', status: body.status, updated_at: '2026-10-02T00:00:00' })
    })
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, detail),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))
    const region = await screen.findByRole('region', { name: 'Board does not load' })

    fireEvent.change(within(region).getByRole('combobox', { name: 'Status' }), { target: { value: 'waiting' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    expect(await within(region).findByText('Ticket updated')).toBeInTheDocument()
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({ status: 'waiting' })

    fireEvent.change(within(region).getByRole('combobox', { name: 'Decided impact' }), { target: { value: '' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2))
    expect(JSON.parse(String(patch.mock.calls[1][0].body))).toEqual({ status: 'waiting', severity: '' })
  })

  it('does not send a decision put back as the ticket stores it, so another admin\'s made meanwhile is kept', async () => {
    const patch = vi.fn((init: RequestInit) => {
      void init
      return response(200, { ticket_num: 'BUG-0001', status: 'waiting', updated_at: '2026-10-02T00:00:00' })
    })
    let detail: Record<string, unknown> = {
      ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
      decided_severity: null, decided_category: null, decided_by: null,
    }
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, detail),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))
    const region = await screen.findByRole('region', { name: 'Board does not load' })
    const impact = () => within(region).getByRole('combobox', { name: 'Decided impact' })

    fireEvent.change(impact(), { target: { value: 'high' } })
    fireEvent.change(impact(), { target: { value: '' } })
    // Another admin decides meanwhile: the form shows it, since nothing is edited here.
    detail = { ...detail, decided_severity: 'critical', decided_by: 'b@acme.test' }
    await act(() => queryClient.invalidateQueries())
    await waitFor(() => expect(impact()).toHaveValue('critical'))

    fireEvent.change(within(region).getByRole('combobox', { name: 'Status' }), { target: { value: 'waiting' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({ status: 'waiting' })
  })

  it('follows the status and resolution another admin saved: a category change does not reopen the ticket', async () => {
    const patch = vi.fn((init: RequestInit) => {
      void init
      return response(200, { ticket_num: 'BUG-0001', status: 'resolved', updated_at: '2026-10-02T00:00:00' })
    })
    let detail: Record<string, unknown> = {
      ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
    }
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, detail),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))
    const region = await screen.findByRole('region', { name: 'Board does not load' })
    expect(within(region).getByRole('combobox', { name: 'Status' })).toHaveValue('open')

    detail = { ...detail, status: 'resolved', resolution: 'Restarted the worker', resolved_at: '2026-10-02T00:00:00' }
    await act(() => queryClient.invalidateQueries())
    await waitFor(() => expect(within(region).getByRole('combobox', { name: 'Status' })).toHaveValue('resolved'))
    expect(within(region).getByRole('textbox', { name: 'Resolution' })).toHaveValue('Restarted the worker')

    fireEvent.change(within(region).getByRole('combobox', { name: 'Decided category' }), { target: { value: 'bug' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({
      status: 'resolved', resolution: 'Restarted the worker', category: 'bug',
    })
  })

  it('does not clear a decision another admin made while the form was open', async () => {
    const patch = vi.fn((init: RequestInit) => {
      void init
      return response(200, { ticket_num: 'BUG-0001', status: 'waiting', updated_at: '2026-10-02T00:00:00' })
    })
    let detail: Record<string, unknown> = {
      ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
      decided_severity: null, decided_category: null, decided_by: null,
    }
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, detail),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))
    const region = await screen.findByRole('region', { name: 'Board does not load' })

    // Another admin decides meanwhile, and the page refetches the ticket.
    detail = { ...detail, decided_severity: 'critical', decided_by: 'b@acme.test' }
    await act(() => queryClient.invalidateQueries())
    expect(await within(region).findByText(/last changed by b@acme.test/)).toBeInTheDocument()

    fireEvent.change(within(region).getByRole('combobox', { name: 'Status' }), { target: { value: 'waiting' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({ status: 'waiting' })
  })

  it('follows the ticket after a save: a later clear is sent, and a decision made then is kept', async () => {
    let detail: Record<string, unknown> = {
      ...TICKET, description: 'Spinner forever', steps: null, expected: null, actual: null, resolution: null,
      decided_severity: null, decided_category: null, decided_by: null,
    }
    const patch = vi.fn((init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      if ('severity' in body) detail = { ...detail, decided_severity: body.severity || null, decided_by: 'admin@acme.test' }
      return response(200, { ticket_num: 'BUG-0001', status: body.status, updated_at: '2026-10-02T00:00:00' })
    })
    stubApi({
      'GET /v1/support/tickets/BUG-0001': () => response(200, detail),
      'PATCH /v1/support/tickets/BUG-0001': patch,
    })
    renderAs(true)
    fireEvent.click(await screen.findByRole('button', { name: /Board does not load/ }))
    const region = await screen.findByRole('region', { name: 'Board does not load' })
    const impact = () => within(region).getByRole('combobox', { name: 'Decided impact' })

    fireEvent.change(impact(), { target: { value: 'high' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    expect(await within(region).findByText(/last changed by admin@acme.test/)).toBeInTheDocument()
    expect(JSON.parse(String(patch.mock.calls[0][0].body))).toEqual({ status: 'open', severity: 'high' })

    // Back to undecided after the save: the clear is a change from what is stored.
    fireEvent.change(impact(), { target: { value: '' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2))
    expect(JSON.parse(String(patch.mock.calls[1][0].body))).toEqual({ status: 'open', severity: '' })

    // Another admin decides next; the form shows it, and a status save leaves it alone.
    await waitFor(() => expect(detail.decided_severity).toBeNull())
    detail = { ...detail, decided_severity: 'low', decided_by: 'b@acme.test' }
    await act(() => queryClient.invalidateQueries())
    await waitFor(() => expect(impact()).toHaveValue('low'))
    fireEvent.change(within(region).getByRole('combobox', { name: 'Status' }), { target: { value: 'waiting' } })
    fireEvent.click(within(region).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(3))
    expect(JSON.parse(String(patch.mock.calls[2][0].body))).toEqual({ status: 'waiting' })
  })

  it("lists the decided impact, else the reporter's marked as theirs", async () => {
    stubApi({
      'GET /v1/support/tickets': () => response(200, {
        tickets: [
          TICKET,
          { ...TICKET, id: 2, ticket_num: 'BUG-0002', title: 'Decided one', decided_severity: 'critical' },
          { ...TICKET, id: 3, ticket_num: 'BUG-0003', title: 'Nobody chose', severity: null },
        ],
        count: 3,
      }),
    })
    renderAs(true)

    expect(await screen.findByRole('button', { name: /Board does not load/ })).toHaveTextContent('High (reported)')
    const decided = screen.getByRole('button', { name: /Decided one/ })
    expect(decided).toHaveTextContent('Critical')
    expect(decided).not.toHaveTextContent('(reported)')
    expect(screen.getByRole('button', { name: /Nobody chose/ })).toHaveTextContent('—')
  })

  it("shows how the agent's suggestions compared with the decisions, beside the reporters'", async () => {
    stubApi({
      'GET /v1/support/agent_record': () => response(200, {
        severity: { decided: 4, agent_agreed: 3, agent_unusable: 0, reporter_chose: 4, reporter_agreed: 1 },
        category: { decided: 0, agent_agreed: 0, agent_unusable: 0, reporter_chose: 0, reporter_agreed: 0 },
      }),
    })
    renderAs(true)

    const record = await screen.findByRole('region', { name: "The Support agent's record" })
    expect(record).toHaveTextContent('Impact: the agent matched 3 of 4 decisions; the reporters 1 of 4.')
    // No category decided yet: no line for it.
    expect(record).not.toHaveTextContent('Category:')
  })

  it("counts the agent's unusable answers, and the reporters only where they chose", async () => {
    stubApi({
      'GET /v1/support/agent_record': () => response(200, {
        severity: { decided: 4, agent_agreed: 2, agent_unusable: 1, reporter_chose: 3, reporter_agreed: 1 },
        category: { decided: 2, agent_agreed: 2, agent_unusable: 0, reporter_chose: 0, reporter_agreed: 0 },
      }),
    })
    renderAs(true)

    const record = await screen.findByRole('region', { name: "The Support agent's record" })
    expect(record).toHaveTextContent('Impact: the agent matched 2 of 4 decisions (1 without a usable answer); the reporters 1 of 3.')
    expect(record).toHaveTextContent('Category: the agent matched 2 of 2 decisions; no reporter chose one.')
  })

  it('shows no record before anything was decided', async () => {
    const fetch = stubApi()
    renderAs(true)
    expect(await screen.findByText('Board does not load')).toBeInTheDocument()
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).includes('/v1/support/agent_record'))).toBe(true))
    expect(screen.queryByRole('region', { name: "The Support agent's record" })).not.toBeInTheDocument()
  })
})

