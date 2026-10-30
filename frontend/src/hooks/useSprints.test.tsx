import { renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QUERY_KEYS, useSprints } from './useQueries'
import { api } from '../services/api'
import { queryClient } from '../lib/queryClient'

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useSprints', () => {
  afterEach(() => {
    queryClient.clear()
    vi.restoreAllMocks()
  })

  it('caches each company under its own key', async () => {
    const list = vi.spyOn(api, 'listSprints').mockImplementation(async companyId => [
      { id: companyId, sprint_name: `Sprint of ${companyId}`, status: 'active', goal: null, start_date: null, scope_size: 'M', total: 0, done: 0, blocked: 0, rework: 0, second_attempts: { total: 0, done: 0, briefed: 0, briefed_done: 0 }, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } } },
    ])
    const { result, rerender } = renderHook(({ companyId }) => useSprints(companyId), { wrapper, initialProps: { companyId: 1 } })
    await waitFor(() => expect(result.current.data?.[0].sprint_name).toBe('Sprint of 1'))
    rerender({ companyId: 2 })
    await waitFor(() => expect(result.current.data?.[0].sprint_name).toBe('Sprint of 2'))
    expect(list.mock.calls).toEqual([[1], [2]])
    expect(QUERY_KEYS.sprints(2)).toEqual(['sprints', 2])
    expect(queryClient.getQueryData(['sprints', 1])).toEqual([expect.objectContaining({ id: 1 })])
  })

  it('does not request without a company', () => {
    const list = vi.spyOn(api, 'listSprints')
    const { result } = renderHook(() => useSprints(null), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')
    expect(list).not.toHaveBeenCalled()
  })

  it('requests GET /v1/sprints with the company id', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue([])
    await api.listSprints(42)
    expect(get).toHaveBeenCalledWith('/v1/sprints', { company_id: 42 })
  })
})
