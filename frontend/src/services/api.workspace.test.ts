import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, errorDetail } from './api'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

describe('workspace API', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
  })

  it('passes a Windows path through as an opaque, encoded query parameter', async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, { path: 'C:\\Users\\ana' }))
    vi.stubGlobal('fetch', fetch)

    await api.browseWorkspace('C:\\Users\\ana\\source repos')
    const url = new URL(fetch.mock.calls[0][0])
    expect(url.pathname).toBe('/v1/workspace/browse')
    expect(url.searchParams.get('path')).toBe('C:\\Users\\ana\\source repos')
    expect(new Headers(fetch.mock.calls[0][1].headers).get('Authorization')).toBe('Bearer valid-token')

    await api.browseWorkspace()
    expect(new URL(fetch.mock.calls[1][0]).search).toBe('')

    await api.inspectWorkspace('~/code/app')
    const inspect = new URL(fetch.mock.calls[2][0])
    expect(inspect.pathname).toBe('/v1/workspace/inspect')
    expect(inspect.searchParams.get('path')).toBe('~/code/app')
  })

  it('does not retry a 503 and keeps the server detail', async () => {
    const fetch = vi.fn().mockResolvedValue(response(503, { detail: 'Workspace daemon not connected' }))
    vi.stubGlobal('fetch', fetch)

    const error = await api.browseWorkspace().catch(err => err)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 503, detail: 'Workspace daemon not connected' })
    expect(errorDetail(error)).toBe('Workspace daemon not connected')
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('falls back to the generic message when an error has no detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => { throw new Error('not json') } }))
    const error = await api.inspectWorkspace('/nope').catch(err => err)
    expect(error).toMatchObject({ status: 404, detail: undefined })
    expect(errorDetail(error)).toBe('Resource not found.')
  })
})
