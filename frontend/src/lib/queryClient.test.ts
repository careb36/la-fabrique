import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { queryClient } from './queryClient'

describe('session query cache isolation', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    queryClient.clear()
    useAuthStore.getState().logout()
  })

  it('logout removes cached data from the shared client (issue #4)', () => {
    queryClient.setQueryData(['sprint-board', 5], { private: 'previous session' })
    expect(queryClient.getQueryData(['sprint-board', 5])).toBeDefined()

    useAuthStore.getState().logout()

    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(queryClient.getQueryData(['sprint-board', 5])).toBeUndefined()
  })

  it('login clears the shared cache before waiting for credentials (issue #4)', async () => {
    queryClient.setQueryData(['sprint-board', 5], { private: 'previous session' })
    let rejectLogin!: (error: Error) => void
    vi.spyOn(api, 'login').mockReturnValue(new Promise((_, reject) => { rejectLogin = reject }))

    const login = useAuthStore.getState().login('next@example.com', 'password')
    const cachedQueries = queryClient.getQueryCache().getAll()
    rejectLogin(new Error('Login failed'))
    await expect(login).rejects.toThrow('Login failed')

    expect(cachedQueries).toHaveLength(0)
  })
})
