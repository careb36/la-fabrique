import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../services/api'
import { useSearchMemory } from './useQueries'

describe('memory search cache', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches the same query separately for different companies', async () => {
    const searchMemory = vi.spyOn(api, 'searchMemory').mockResolvedValue({ results: [] })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { rerender } = renderHook(
      ({ companyId }) => useSearchMemory('auth', companyId),
      { initialProps: { companyId: 1 }, wrapper },
    )

    await waitFor(() => expect(searchMemory).toHaveBeenCalledTimes(1))
    act(() => rerender({ companyId: 2 }))
    await waitFor(() => expect(searchMemory).toHaveBeenCalledTimes(2))

    expect(searchMemory).toHaveBeenNthCalledWith(1, 'auth', { companyId: 1, limit: 10 })
    expect(searchMemory).toHaveBeenNthCalledWith(2, 'auth', { companyId: 2, limit: 10 })
    queryClient.clear()
  })
})
