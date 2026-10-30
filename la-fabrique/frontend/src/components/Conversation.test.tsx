import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Conversation } from './Conversation'
import { queryClient } from '../lib/queryClient'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

const MESSAGES = [
  {
    id: 1, sprint_id: 8, backlog_item_id: 31, task_title: 'Login form', from_name: 'Dev', from_role: 'Developer',
    to_role: 'QA', kind: 'handoff', body: 'Delivered "Login form" for review: 1 file(s) declared — src/login.py.',
    created_at: '2026-10-18T10:00:00Z',
  },
  {
    id: 2, sprint_id: 8, backlog_item_id: 31, task_title: 'Login form', from_name: 'Quinn', from_role: 'QA',
    to_role: 'Developer', kind: 'request', body: `NEEDS WORK: ${'validate the email. '.repeat(30)}`,
    created_at: '2026-10-18T10:05:00Z',
  },
  {
    id: 3, sprint_id: 8, backlog_item_id: null, task_title: null, from_name: 'ScrumMaster', from_role: 'ScrumMaster',
    to_role: null, kind: 'retrospective', body: 'Sprint 8 retrospective: completed 1/1 tasks',
    created_at: '2026-10-18T11:00:00Z',
  },
]

function renderConversation(props: { sprintId?: number; taskId?: number }) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Conversation companyId={4} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Conversation', () => {
  beforeEach(() => {
    queryClient.clear()
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it("shows the sprint's messages with who spoke to whom, and filters by kind", async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { messages: MESSAGES }))
    vi.stubGlobal('fetch', fetch)
    renderConversation({ sprintId: 8 })

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('Dev')
    expect(items[0]).toHaveTextContent('Developer')
    expect(items[0]).toHaveTextContent('QA')
    expect(items[0]).toHaveTextContent('Handoff')
    expect(within(items[0]).getByRole('link', { name: 'Login form' })).toHaveAttribute('href', '/sprints/8/tasks/31')
    expect(items[2]).toHaveTextContent('the team')
    expect(items[2]).toHaveTextContent('Retrospective')

    // Long messages are folded.
    expect(items[1]).toHaveTextContent('…')
    fireEvent.click(within(items[1]).getByRole('button', { name: 'Show more' }))
    expect(within(items[1]).getByRole('button', { name: 'Show less' })).toBeInTheDocument()

    let url = new URL(fetch.mock.calls[0][0])
    expect(url.pathname).toBe('/v1/messages')
    expect(Object.fromEntries(url.searchParams)).toEqual({ company_id: '4', sprint_id: '8' })

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'escalation' } })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    url = new URL(fetch.mock.calls[1][0])
    expect(url.searchParams.get('kind')).toBe('escalation')
  })

  it("lists one task's thread without the kind filter or task links", async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { messages: MESSAGES.slice(0, 2) }))
    vi.stubGlobal('fetch', fetch)
    renderConversation({ taskId: 31 })

    expect(await screen.findAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Login form' })).not.toBeInTheDocument()
    expect(new URL(fetch.mock.calls[0][0]).searchParams.get('backlog_item_id')).toBe('31')
  })

  it('says when there is nothing yet, and offers a retry when loading fails', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(403, { detail: 'Not a member of this company' }))
      .mockResolvedValueOnce(response(200, { messages: [] }))
    vi.stubGlobal('fetch', fetch)
    renderConversation({ sprintId: 8 })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the conversation.')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument()
  })
})
