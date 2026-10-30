import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CompanyMembers from './CompanyMembers'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

function renderAs(role: 'Owner' | 'Manager' | 'Viewer') {
  useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000, memberships: [{ company_id: 4, human_role: role }] })
  return render(
    <QueryClientProvider client={queryClient}>
      <CompanyMembers />
    </QueryClientProvider>,
  )
}

describe('CompanyMembers', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4, companyName: 'Acme' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('tells a non-owner that only owners invite', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    renderAs('Manager')
    expect(screen.getByRole('status')).toHaveTextContent('Only owners can invite members. Your role here is Manager.')
    expect(screen.queryByRole('button', { name: 'Invite' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('invites with the role chosen, and explains a 404 as a missing account', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(404, { detail: 'User not found' }))
      .mockResolvedValueOnce(response(200, { status: 'success', message: 'ok' }))
    vi.stubGlobal('fetch', fetch)
    renderAs('Owner')

    fireEvent.change(screen.getByRole('textbox', { name: 'Email of their account' }), { target: { value: ' ana@acme.test ' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Role' }), { target: { value: 'Manager' } })
    fireEvent.click(screen.getByRole('button', { name: 'Invite' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('There is no account with that email')
    const [url, init] = fetch.mock.calls[0]
    expect(new URL(url).pathname).toBe('/v1/company/invite')
    expect(JSON.parse(init.body)).toEqual({ company_id: 4, email: 'ana@acme.test', human_role: 'Manager' })

    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('ana@acme.test can now work here as Manager.')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Email of their account' })).toHaveValue('')
  })

  it('says when the person is already a member', async () => {
    const fetch = vi.fn().mockResolvedValue(response(409, { detail: 'ana@acme.test is already a member as Viewer' }))
    vi.stubGlobal('fetch', fetch)
    renderAs('Owner')

    fireEvent.change(screen.getByRole('textbox', { name: 'Email of their account' }), { target: { value: 'ana@acme.test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Invite' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('They are already a member of this company.')
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
