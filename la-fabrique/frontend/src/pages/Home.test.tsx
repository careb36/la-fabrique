import { render, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { api } from '../services/api'
import { queryClient } from '../lib/queryClient'
import { useAuthStore } from '../store/useAuthStore'
import { useAppStore } from '../store/useAppStore'

afterEach(() => {
  queryClient.clear()
  vi.restoreAllMocks()
  useAuthStore.getState().logout()
})

describe('Home redirect', () => {
  it('replaces / with Evidence for an authenticated company member', async () => {
    useAuthStore.setState({
      token: 'signed-token', expiresAt: Date.now() + 60_000,
      meLoaded: true, loadingMe: false,
      memberships: [{ company_id: 1, human_role: 'Owner' }],
    })
    useAppStore.setState({ companyId: 1, companyName: 'Example', activeSprintId: null })
    vi.spyOn(api, 'capabilities').mockResolvedValue({ agent_graph: false, memory: false, github: false, auth_required: true })
    vi.spyOn(api, 'getAgentRuns').mockResolvedValue({ agent_runs: [] } as never)
    window.history.replaceState(null, '', '/')
    const historyLength = window.history.length

    render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)

    await waitFor(() => expect(window.location.pathname).toBe('/evidence'))
    expect(window.history.length).toBe(historyLength)
  })
})
