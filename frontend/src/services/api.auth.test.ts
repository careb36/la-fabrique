import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setOnUnauthorized } from './api'
import { useAuthStore } from '../store/useAuthStore'
import { useAppStore } from '../store/useAppStore'

function response(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

describe('authenticated API requests', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    useAppStore.getState().setCompany(null, null)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, { ok: true })))
  })

  afterEach(() => {
    setOnUnauthorized(null)
    vi.unstubAllGlobals()
  })

  it('sends the bearer token when a valid token is stored', async () => {
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })

    await api.get('/v1/protected')

    const request = vi.mocked(fetch).mock.calls[0][1]!
    expect(new Headers(request.headers).get('Authorization')).toBe(
      ['Bearer', ['valid', 'token'].join('-')].join(' '),
    )
  })

  it('omits the bearer token when no token is stored', async () => {
    await api.get('/v1/public')

    const request = vi.mocked(fetch).mock.calls[0][1]!
    expect(new Headers(request.headers).has('Authorization')).toBe(false)
  })

  it('treats an expired token as absent', async () => {
    useAuthStore.setState({ token: 'expired-token', expiresAt: Date.now() - 1 })

    await api.get('/v1/protected')

    const request = vi.mocked(fetch).mock.calls[0][1]!
    expect(new Headers(request.headers).has('Authorization')).toBe(false)
    expect(useAuthStore.getState().token).toBeNull()
  })

  it('clears auth and invokes the hook for protected 401s, but not login 401s', async () => {
    const onUnauthorized = vi.fn()
    setOnUnauthorized(onUnauthorized)
    useAuthStore.setState({
      token: 'valid-token',
      expiresAt: Date.now() + 60_000,
      user: { user_id: 1, email: 'user@example.com', full_name: 'User' },
    })
    vi.mocked(fetch).mockResolvedValue(response(401))

    await expect(api.get('/v1/protected')).rejects.toBeInstanceOf(ApiError)
    expect(useAuthStore.getState().token).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledOnce()

    useAuthStore.setState({ token: 'still-valid', expiresAt: Date.now() + 60_000 })
    onUnauthorized.mockClear()
    await expect(api.login('user@example.com', 'wrong')).rejects.toBeInstanceOf(ApiError)
    expect(useAuthStore.getState().token).toBe('still-valid')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('handles parallel 401s for the same token only once (issue #1)', async () => {
    const onUnauthorized = vi.fn()
    setOnUnauthorized(onUnauthorized)
    useAuthStore.setState({ token: 'rejected-token', expiresAt: Date.now() + 60_000 })
    let rejectRequests!: (value: Response) => void
    vi.mocked(fetch).mockReturnValue(new Promise(resolve => { rejectRequests = resolve }))

    const requests = Promise.allSettled([api.get('/v1/first'), api.get('/v1/second')])
    expect(fetch).toHaveBeenCalledTimes(2)
    rejectRequests(response(401))
    expect((await requests).every(result => result.status === 'rejected')).toBe(true)

    expect(useAuthStore.getState().token).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('does not log out a newer session for a stale 401 (issue #1)', async () => {
    const onUnauthorized = vi.fn()
    setOnUnauthorized(onUnauthorized)
    useAuthStore.setState({ token: 'old-token', expiresAt: Date.now() + 60_000 })
    let rejectRequest!: (value: Response) => void
    vi.mocked(fetch).mockReturnValue(new Promise(resolve => { rejectRequest = resolve }))
    const request = api.get('/v1/protected')
    useAuthStore.setState({ token: 'new-token' })

    rejectRequest(response(401))
    await expect(request).rejects.toBeInstanceOf(ApiError)

    expect(useAuthStore.getState().token).toBe('new-token')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('does not invoke the unauthorized hook without a sent token (issue #1)', async () => {
    const onUnauthorized = vi.fn()
    setOnUnauthorized(onUnauthorized)
    vi.mocked(fetch).mockResolvedValue(response(401))

    await expect(api.get('/v1/protected')).rejects.toBeInstanceOf(ApiError)

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
