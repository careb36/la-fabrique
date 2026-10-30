import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { useAgentStore } from './agentStore'
import { useAuthStore } from './useAuthStore'
import { SSE_RECONNECT_DELAY_MS } from '../lib/constants'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

class FakeEventSource {
  static opened: FakeEventSource[] = []
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    FakeEventSource.opened.push(this)
  }
}

describe('Glassroom stream connection', () => {
  beforeEach(() => {
    FakeEventSource.opened = []
    vi.stubGlobal('EventSource', FakeEventSource)
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
  })

  afterEach(() => {
    useAgentStore.getState().disconnect()
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
  })

  it('opens the stream with a ticket for the sprint, asked for on every connection', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(200, { ticket: 'ticket-1', expires_in: 300 }))
      .mockResolvedValueOnce(response(200, { ticket: 'ticket-2', expires_in: 300 }))
    vi.stubGlobal('fetch', fetch)

    useAgentStore.getState().connect('7')
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(1))
    const first = new URL(FakeEventSource.opened[0].url)
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/v1/sprints/7/stream_ticket')
    expect(fetch.mock.calls[0][1].method).toBe('POST')
    expect(Object.fromEntries(first.searchParams)).toEqual({ sprint_id: '7', ticket: 'ticket-1' })

    // A ticket is short-lived: reconnecting asks for a new one.
    useAgentStore.getState().connect('7')
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(2))
    expect(new URL(FakeEventSource.opened[1].url).searchParams.get('ticket')).toBe('ticket-2')
  })

  it('opens it without a ticket when none is needed or none could be had', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(200, { ticket: null, expires_in: 0 }))
      .mockResolvedValueOnce(response(403, { detail: 'Not a member of this company' }))
    vi.stubGlobal('fetch', fetch)

    useAgentStore.getState().connect('7')
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(1))
    expect(new URL(FakeEventSource.opened[0].url).searchParams.has('ticket')).toBe(false)

    useAgentStore.getState().connect('7')
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(2))
    expect(new URL(FakeEventSource.opened[1].url).searchParams.has('ticket')).toBe(false)
  })

  it('does not open a stream once disconnected while the ticket was on its way', async () => {
    let answer: (value: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { answer = resolve })))

    useAgentStore.getState().connect('7')
    useAgentStore.getState().disconnect()
    answer(response(200, { ticket: 'late', expires_in: 300 }))
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(FakeEventSource.opened).toHaveLength(0)
  })
})

describe('Glassroom replayed history', () => {
  // What the backend replays on every connection: a past comment of task 3.
  const replayed = {
    type: 'agent_complete', semantic_type: 'task.history_comment', source: 'history', semantic_version: 1,
    event_id: 'history-3-0', agent: 'Developer', role: 'Developer', task_id: 3, task: 'Login form',
    message: '✅ Developer delivered: Login form', timestamp: '2026-10-01T10:00:00',
  }

  function deliver(source: FakeEventSource, event: Record<string, unknown>) {
    source.onmessage?.({ data: JSON.stringify(event) } as MessageEvent)
  }

  beforeEach(() => {
    FakeEventSource.opened = []
    vi.stubGlobal('EventSource', FakeEventSource)
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
    useAgentStore.getState().clearMessages()
  })

  afterEach(() => {
    useAgentStore.getState().disconnect()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
  })

  it('shows an event replayed after a reconnection once', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(200, { ticket: 't', expires_in: 300 })))
    useAgentStore.getState().connect('7')
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(1))
    deliver(FakeEventSource.opened[0], replayed)
    expect(useAgentStore.getState().messages).toHaveLength(1)

    // The connection drops; the store reconnects after its delay, and the
    // backend replays the same history before anything new.
    vi.useFakeTimers()
    FakeEventSource.opened[0].onerror?.()
    await vi.advanceTimersByTimeAsync(SSE_RECONNECT_DELAY_MS)
    vi.useRealTimers()
    await waitFor(() => expect(FakeEventSource.opened).toHaveLength(2))
    deliver(FakeEventSource.opened[1], replayed)
    deliver(FakeEventSource.opened[1], { ...replayed, event_id: 'history-3-1', message: '✅ QA delivered: Login form' })

    expect(useAgentStore.getState().messages.map(m => m.eventId)).toEqual(['history-3-0', 'history-3-1'])
  })

  it('keeps every event without an id, and shows a replay again after a fresh connection', () => {
    const { addMessage, clearMessages } = useAgentStore.getState()
    const base = { timestamp: '2026-10-01T10:00:00', agent: 'System', content: 'x', type: 'status' as const }
    addMessage({ ...base, id: 'a' })
    addMessage({ ...base, id: 'b' })
    addMessage({ ...base, id: 'c', eventId: 'live-1' })
    addMessage({ ...base, id: 'd', eventId: 'live-1' })
    expect(useAgentStore.getState().messages.map(m => m.id)).toEqual(['a', 'b', 'c'])

    // connect() clears the messages: the next replay shows the history again.
    clearMessages()
    addMessage({ ...base, id: 'e', eventId: 'live-1' })
    expect(useAgentStore.getState().messages.map(m => m.id)).toEqual(['e'])
  })
})
