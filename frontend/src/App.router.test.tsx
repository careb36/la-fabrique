import { render } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'
import { queryClient } from './lib/queryClient'
import { api } from './services/api'
import { useAuthStore } from './store/useAuthStore'

afterEach(() => {
  queryClient.clear()
  vi.restoreAllMocks()
})

it('does not emit React Router future-flag warnings on the first router render', () => {
  useAuthStore.getState().logout()
  window.history.replaceState(null, '', '/login')
  vi.spyOn(api, 'capabilities').mockResolvedValue({ agent_graph: false, memory: false, github: false, auth_required: true })
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

  render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>)

  expect(warn.mock.calls.flat().join(' ')).not.toMatch(/React Router Future Flag Warning/)
})
