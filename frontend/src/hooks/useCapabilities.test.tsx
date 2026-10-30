import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useCapabilities } from './useQueries'
import { api } from '../services/api'
import { queryClient } from '../lib/queryClient'
import { useAuthStore } from '../store/useAuthStore'

const capabilities = { agent_graph: true, memory: false, github: false, auth_required: true }

afterEach(() => {
  queryClient.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  useAuthStore.getState().logout()
})

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('capabilities', () => {
  it('requests the public endpoint without a bearer even when logged in', async () => {
    useAuthStore.setState({ token: 'signed-token', expiresAt: Date.now() + 60_000 })
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => capabilities })
    vi.stubGlobal('fetch', fetch)

    expect(await api.capabilities()).toEqual(capabilities)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/v1/capabilities'), expect.objectContaining({ method: 'GET' }))
    expect(new Headers(fetch.mock.calls[0][1].headers).has('Authorization')).toBe(false)
    expect(useAuthStore.getState().token).toBe('signed-token')
  })

  it('reuses capability data for five minutes and refetches once stale', async () => {
    const request = vi.spyOn(api, 'capabilities').mockResolvedValue(capabilities)
    const first = renderHook(() => useCapabilities(), { wrapper })
    await waitFor(() => expect(first.result.current.data).toEqual(capabilities))
    first.unmount()

    const second = renderHook(() => useCapabilities(), { wrapper })
    expect(second.result.current.data).toEqual(capabilities)
    expect(request).toHaveBeenCalledTimes(1)
    second.unmount()

    act(() => queryClient.setQueryData(['capabilities'], capabilities, { updatedAt: Date.now() - 5 * 60_000 - 1 }))
    const third = renderHook(() => useCapabilities(), { wrapper })
    await waitFor(() => expect(third.result.current.isFetching).toBe(false))
    expect(request).toHaveBeenCalledTimes(2)
  })
})
