import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SupportBot } from './SupportBot'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function requestTo(fetch: ReturnType<typeof vi.fn>, pathname: string) {
  const call = fetch.mock.calls.find(([url]) => new URL(url).pathname === pathname)
  expect(call, `no request to ${pathname}`).toBeDefined()
  return { url: new URL(call![0]), init: call![1] as RequestInit }
}

describe('SupportBot', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
    // jsdom has no layout: the chat scrolls its last message into view.
    Element.prototype.scrollIntoView = vi.fn()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
  })

  it('sends the conversation as `messages`, the body the support chat endpoint reads', async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { reply: 'Hola, ¿en qué te ayudo?' }))
    vi.stubGlobal('fetch', fetch)
    render(<SupportBot />)

    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'How do I start a sprint?' } })
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })

    expect(await screen.findByText('Hola, ¿en qué te ayudo?')).toBeInTheDocument()
    const { init } = requestTo(fetch, '/v1/support/chat')
    const body = JSON.parse(init.body as string)
    expect(body).not.toHaveProperty('message')
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: 'How do I start a sprint?' })
    expect(body.messages[0].role).toBe('assistant')
  })

  it('reports no impact the reporter did not choose, and the one they did', async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { ticket_num: 'FAB-00001', status: 'open' }))
    vi.stubGlobal('fetch', fetch)
    render(<SupportBot />)
    const submit = () => {
      fireEvent.change(screen.getByPlaceholderText("e.g. Sprint board won't load"), { target: { value: 'Board' } })
      fireEvent.change(screen.getByPlaceholderText(/Describe what you were doing/), { target: { value: 'Spins' } })
      fireEvent.click(screen.getByRole('button', { name: 'Submit Report' }))
    }
    const sent = () => JSON.parse(String(fetch.mock.calls.at(-1)![1].body))

    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.click(screen.getByTitle('Report a Problem'))
    // Nothing preset: a preset would pass for the reporter's choice.
    expect(screen.getByRole('combobox')).toHaveValue('')
    submit()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Submit Report' })).not.toBeInTheDocument())
    expect(sent()).not.toHaveProperty('severity')

    fireEvent.click(screen.getByTitle('Report a Problem'))
    expect(screen.getByRole('combobox')).toHaveValue('')
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'high' } })
    submit()
    await waitFor(() => expect(sent().severity).toBe('high'))
  })

  it('looks tickets up on the support endpoints', async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { tickets: [], count: 0 }))
    vi.stubGlobal('fetch', fetch)
    render(<SupportBot />)

    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.click(screen.getByTitle('My Tickets'))
    const email = screen.getByPlaceholderText(/email/i)
    fireEvent.change(email, { target: { value: 'ana@example.com' } })
    fireEvent.keyDown(email, { key: 'Enter' })

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const { url } = requestTo(fetch, '/v1/support/tickets')
    expect(url.searchParams.get('reporter_email')).toBe('ana@example.com')
  })

  it("shows the reporter the Support agent's first reply", async () => {
    useAuthStore.setState({ user: { user_id: 3, email: 'me@example.com', full_name: 'Me' } })
    const fetch = vi.fn(async (url: string) => {
      const { pathname } = new URL(url)
      if (pathname === '/v1/support/tickets') {
        return response(200, { tickets: [{ ticket_num: 'FAB-00009', title: 'Board', status: 'in_progress', severity: 'low', created_at: null }], count: 1 })
      }
      return response(200, {
        ticket_num: 'FAB-00009', title: 'Board', status: 'in_progress', severity: 'low', category: 'bug',
        description: 'Spinner', created_at: null, updated_at: null, resolved_at: null, resolution: null,
        agent_reply: 'Gracias, ya lo estamos viendo.',
      })
    })
    vi.stubGlobal('fetch', fetch)
    render(<SupportBot />)

    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.click(screen.getByTitle('My Tickets'))
    fireEvent.keyDown(screen.getByPlaceholderText(/email/i), { key: 'Enter' })
    fireEvent.click(await screen.findByText('FAB-00009'))

    expect(await screen.findByText('Reply from the Support agent')).toBeInTheDocument()
    expect(screen.getByText('Gracias, ya lo estamos viendo.')).toBeInTheDocument()
  })

  it('fills in the account email once the profile loads', async () => {
    vi.stubGlobal('fetch', vi.fn())
    render(<SupportBot />)
    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.click(screen.getByTitle('My Tickets'))
    expect(screen.getByPlaceholderText(/email/i)).toHaveValue('')

    act(() => useAuthStore.setState({ user: { user_id: 3, email: 'late@example.com', full_name: 'Late' } }))
    expect(screen.getByPlaceholderText(/email/i)).toHaveValue('late@example.com')
  })

  it("starts from the account email and explains a refusal for someone else's", async () => {
    useAuthStore.setState({ user: { user_id: 3, email: 'me@example.com', full_name: 'Me' } })
    const fetch = vi.fn().mockResolvedValue(response(403, { detail: 'You can only see your own tickets' }))
    vi.stubGlobal('fetch', fetch)
    render(<SupportBot />)

    fireEvent.click(screen.getByTitle('Open Support'))
    fireEvent.click(screen.getByTitle('My Tickets'))
    const email = screen.getByPlaceholderText(/email/i)
    expect(email).toHaveValue('me@example.com')
    fireEvent.change(email, { target: { value: 'boss@example.com' } })
    fireEvent.keyDown(email, { key: 'Enter' })

    expect(await screen.findByText('You can only see the tickets reported with your account email (me@example.com).'))
      .toBeInTheDocument()
  })
})
