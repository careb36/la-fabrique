import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { adoptHandoff } from './handoff'
import { useAuthStore } from '../store/useAuthStore'

function answer(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status === 200, status, json: async () => body })
}

describe('adoptHandoff', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    window.history.replaceState({}, '', '/evidence')
  })
  afterEach(() => {
    useAuthStore.getState().logout()
  })

  it('trades the code for a session with a POST and scrubs it from the address', async () => {
    window.location.hash = '#codigo=abc'
    const fetchImpl = answer(200, { access_token: 'tok', expires_in: 600 })

    await adoptHandoff(fetchImpl as unknown as typeof fetch)

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toMatch(/\/v1\/auth\/desktop\/redeem$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ code: 'abc' })
    expect(useAuthStore.getState().getValidToken()).toBe('tok')
    expect(window.location.hash).toBe('')
    expect(window.location.pathname).toBe('/evidence')
  })

  it('never replaces a session already open in this browser', async () => {
    useAuthStore.getState().adoptSession('mine', 600)
    window.location.hash = '#codigo=abc'
    const fetchImpl = answer(200, { access_token: 'theirs', expires_in: 600 })

    await adoptHandoff(fetchImpl as unknown as typeof fetch)

    expect(fetchImpl).not.toHaveBeenCalled()
    expect(useAuthStore.getState().getValidToken()).toBe('mine')
    expect(window.location.hash).toBe('')
  })

  it('does not accept a session token in the address', async () => {
    window.location.hash = '#sesion=tok&caduca=600'
    const fetchImpl = answer(200, {})

    await adoptHandoff(fetchImpl as unknown as typeof fetch)

    expect(fetchImpl).not.toHaveBeenCalled()
    expect(useAuthStore.getState().getValidToken()).toBeNull()
  })

  it('a refused code leaves the person signed out', async () => {
    window.location.hash = '#codigo=spent'

    await adoptHandoff(answer(401, { detail: 'Invalid or expired code' }) as unknown as typeof fetch)

    expect(useAuthStore.getState().getValidToken()).toBeNull()
    expect(window.location.hash).toBe('')
  })
})
