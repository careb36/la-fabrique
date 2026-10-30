import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Lineage, { lineagePath } from './Lineage'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname + location.search}</output>
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/lineage" element={<><Lineage /><Location /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function stubApi(lineage: () => Response, memory = true) {
  const fetch = vi.fn(async (url: string) => {
    const { pathname } = new URL(url)
    if (pathname === '/v1/capabilities') return response(200, { agent_graph: false, memory, github: false, auth_required: true })
    if (pathname === '/v1/enterprise/lineage') return lineage()
    return response(404)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('Lineage', () => {
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

  it('builds links that carry the file in the query string', () => {
    expect(lineagePath('src/a b.py')).toBe('/lineage?file=src%2Fa+b.py')
  })

  it('loads the decisions for the file in the URL, scoped to the company', async () => {
    const fetch = stubApi(() => response(200, {
      file: 'src/app.py',
      status: 'success',
      lineage: [
        { engram_id: 'e2', role: 'Architect', decision: 'Split the router', timestamp: '2026-10-02T10:00:00Z', company_id: 4, legacy: false },
        { engram_id: 'e1', role: null, decision: null, timestamp: null, company_id: null, legacy: true },
      ],
    }))
    renderAt('/lineage?file=src%2Fapp.py')

    const list = await screen.findByRole('list', { name: 'Decisions on src/app.py' })
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Architect')
    expect(items[0]).toHaveTextContent('Split the router')
    expect(items[1]).toHaveTextContent('unknown role')
    expect(items[1]).toHaveTextContent('no company')
    expect(items[1]).toHaveTextContent('No summary recorded.')
    const url = new URL(fetch.mock.calls.find(([u]) => u.includes('/lineage'))![0])
    expect(url.searchParams.get('file_path')).toBe('src/app.py')
    expect(url.searchParams.get('company_id')).toBe('4')
  })

  it('puts a typed path in the URL and says when nothing is recorded', async () => {
    stubApi(() => response(200, { file: 'x.ts', status: 'No historical engrams found.', lineage: [] }))
    renderAt('/lineage')

    fireEvent.change(screen.getByRole('textbox', { name: 'File path' }), { target: { value: ' x.ts ' } })
    fireEvent.click(screen.getByRole('button', { name: /show/i }))

    expect(await screen.findByText('No decisions recorded for x.ts.')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/lineage?file=x.ts')
  })

  it('warns when the graph is not connected and offers a retry on failure', async () => {
    const fetch = stubApi(() => response(500, { detail: 'Neo4j Time Travel query failed.' }), false)
    renderAt('/lineage?file=a.py')

    expect(await screen.findByText(/needs the knowledge graph/)).toBeInTheDocument()
    const alert = await screen.findByRole('alert', {}, { timeout: 3000 })
    expect(alert).toHaveTextContent('Neo4j Time Travel query failed.')
    const before = fetch.mock.calls.length
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    await vi.waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(before))
  })
})
