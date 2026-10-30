import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceStatus } from './useQueries'
import { api, ApiError } from '../services/api'

const HOST = { hostname: 'ana-mbp', platform: 'darwin', home: '/Users/ana', sep: '/' }

let client: QueryClient

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  client.clear()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useWorkspaceStatus', () => {
  it('reports the connected host and stops polling', async () => {
    const status = vi.spyOn(api, 'workspaceStatus').mockResolvedValue({ connected: true, host: HOST, jetstream: true })
    const { result } = renderHook(() => useWorkspaceStatus(), { wrapper })

    await waitFor(() => expect(result.current.data?.connected).toBe(true))
    expect(result.current.data?.host).toEqual(HOST)
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(status).toHaveBeenCalledTimes(1)
  })

  it('reports a missing daemon and polls every 10 s until it connects', async () => {
    const status = vi.spyOn(api, 'workspaceStatus')
      .mockResolvedValueOnce({ connected: false, host: null })
      .mockResolvedValueOnce({ connected: false, host: null })
      .mockResolvedValue({ connected: true, host: HOST })
    const { result } = renderHook(() => useWorkspaceStatus(), { wrapper })

    await waitFor(() => expect(result.current.data).toEqual({ connected: false, host: null }))
    expect(status).toHaveBeenCalledTimes(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    await waitFor(() => expect(status).toHaveBeenCalledTimes(2))
    expect(result.current.data?.connected).toBe(false)

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    await waitFor(() => expect(result.current.data?.connected).toBe(true))
    expect(result.current.data?.host?.hostname).toBe('ana-mbp')

    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(status).toHaveBeenCalledTimes(3)
  })

  it('stops polling when the endpoint rejects the client', async () => {
    const status = vi.spyOn(api, 'workspaceStatus').mockRejectedValue(new ApiError(404, 'Resource not found.'))
    const { result } = renderHook(() => useWorkspaceStatus(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(status).toHaveBeenCalledTimes(1)
  })
})
