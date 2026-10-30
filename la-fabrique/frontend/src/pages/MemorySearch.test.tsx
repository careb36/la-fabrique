import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MemorySearch from './MemorySearch'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemorySearch />
    </QueryClientProvider>,
  )
}

describe('MemorySearch', () => {
  beforeEach(() => {
    queryClient.clear()
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000 })
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('searches with the parameters the API reads and lists the results', async () => {
    const fetch = vi.fn().mockResolvedValue(response(200, {
      results: [{ content: 'Use pnpm in this repo', metadata: null, similarity: 0.91 }],
    }))
    vi.stubGlobal('fetch', fetch)
    renderPage()

    fireEvent.change(screen.getByRole('textbox', { name: /search/i }), { target: { value: 'package manager' } })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))

    expect(await screen.findByText('Use pnpm in this repo')).toBeInTheDocument()
    const url = new URL(fetch.mock.calls[0][0])
    expect(url.pathname).toBe('/v1/memory/search')
    expect(url.searchParams.get('query')).toBe('package manager')
    expect(url.searchParams.get('company_id')).toBe('4')
    expect(url.searchParams.get('limit')).toBe('10')
  })

  it('saves a note to memory, and offers a retry when saving fails', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(503, { detail: 'Memory service unavailable (Neo4j not connected).' }))
      .mockResolvedValueOnce(response(200, { status: 'stored' }))
    vi.stubGlobal('fetch', fetch)
    renderPage()

    fireEvent.change(screen.getByRole('textbox', { name: 'Note to remember' }), {
      target: { value: 'Releases are cut on Thursdays' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save to memory' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Neo4j not connected')
    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = fetch.mock.calls[0]
    const parsed = new URL(url)
    expect(parsed.pathname).toBe('/v1/memory/store')
    expect(init.method).toBe('POST')
    expect(parsed.searchParams.get('content')).toBe('Releases are cut on Thursdays')
    expect(parsed.searchParams.get('company_id')).toBe('4')

    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Saved to memory')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Note to remember' })).toHaveValue(''))
  })
})
