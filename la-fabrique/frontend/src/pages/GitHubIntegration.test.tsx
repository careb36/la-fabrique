import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GitHubIntegration, { generateWebhookSecret } from './GitHubIntegration'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

function response(status: number, body: unknown = {}) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response
}

type Handler = (init: RequestInit) => Response

function stubApi(handlers: Record<string, Handler[]>, github = true, publicApiUrl: string | null = null) {
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const { pathname } = new URL(url)
    if (pathname === '/v1/capabilities') {
      return response(200, { agent_graph: false, memory: false, github, auth_required: true, public_api_url: publicApiUrl })
    }
    const queue = handlers[pathname]
    if (!queue?.length) return response(404)
    return queue.length > 1 ? queue.shift()!(init) : queue[0](init)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderAs(role: 'Owner' | 'Manager' | 'Viewer') {
  useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000, memberships: [{ company_id: 4, human_role: role }] })
  return render(
    <QueryClientProvider client={queryClient}>
      <GitHubIntegration />
    </QueryClientProvider>,
  )
}

function fillRepo(section: HTMLElement) {
  fireEvent.change(within(section).getByRole('textbox', { name: 'Owner (user or organization)' }), { target: { value: 'acme' } })
  fireEvent.change(within(section).getByRole('textbox', { name: 'Repository' }), { target: { value: 'app' } })
}

describe('GitHubIntegration', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 4 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.getState().logout()
    queryClient.clear()
  })

  it('generates 64-character hex secrets that differ', () => {
    const secret = generateWebhookSecret()
    expect(secret).toMatch(/^[0-9a-f]{64}$/)
    expect(generateWebhookSecret()).not.toBe(secret)
  })

  it('is closed to viewers', () => {
    stubApi({})
    renderAs('Viewer')
    expect(screen.getByRole('status')).toHaveTextContent('requires the Manager or Owner role. Your role here is Viewer.')
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument()
  })

  it('connects a repository and shows the webhook settings with the secret it sent', async () => {
    const fetch = stubApi({
      '/v1/integrations/github/bindings': [
        () => response(409, { detail: 'Repository already bound' }),
        init => {
          const body = JSON.parse(String(init.body))
          return response(200, { id: 1, company_id: 4, owner: body.owner, repo: body.repo, inclusion_rule: body.inclusion_rule })
        },
      ],
    })
    renderAs('Manager')
    const section = screen.getByRole('region', { name: 'Connect a repository' })
    fillRepo(section)
    fireEvent.change(within(section).getByRole('combobox', { name: 'Pull requests to record' }), { target: { value: 'non_bots' } })
    const secret = (within(section).getByRole('textbox', { name: 'Webhook secret' }) as HTMLInputElement).value
    fireEvent.click(within(section).getByRole('button', { name: 'Connect' }))

    const alert = await within(section).findByRole('alert')
    expect(alert).toHaveTextContent('That repository is already connected.')
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }))

    const done = await within(section).findByRole('status')
    expect(done).toHaveTextContent('acme/app is connected')
    // Same-origin by default: the UI and the API are one process in the packaged product.
    expect(done).toHaveTextContent(`${window.location.origin}/v1/integrations/github/webhook`)
    expect(done).toHaveTextContent(secret)
    expect(within(done).getByRole('link', { name: 'Open the repository webhook settings' }))
      .toHaveAttribute('href', 'https://github.com/acme/app/settings/hooks/new')
    const bindCalls = fetch.mock.calls.filter(([url]) => url.includes('/bindings'))
    expect(JSON.parse(String(bindCalls[1][1]!.body))).toEqual({
      company_id: 4, owner: 'acme', repo: 'app', webhook_secret: secret, inclusion_rule: 'non_bots',
    })
    // A fresh secret is ready for the next repository.
    expect(within(section).getByRole('textbox', { name: 'Webhook secret' })).not.toHaveValue(secret)
  })

  it("uses the backend's public URL for the webhook when it has one", async () => {
    stubApi({
      '/v1/integrations/github/bindings': [() => response(200, { id: 1, company_id: 4, owner: 'acme', repo: 'app', inclusion_rule: 'all' })],
    }, true, 'https://fabrique.example.com')
    renderAs('Owner')
    const section = screen.getByRole('region', { name: 'Connect a repository' })
    fillRepo(section)
    fireEvent.click(within(section).getByRole('button', { name: 'Connect' }))

    const done = await within(section).findByRole('status')
    await vi.waitFor(() => expect(done).toHaveTextContent('https://fabrique.example.com/v1/integrations/github/webhook'))
    expect(done).not.toHaveTextContent('Set PUBLIC_API_URL')
  })

  it('imports past pull requests and lists the ones that failed', async () => {
    const fetch = stubApi({
      '/v1/integrations/github/backfill': [() => response(200, { ingested: 3, skipped: 1, errors: [{ number: 7, error: 'diff too large' }] })],
    }, false)
    renderAs('Owner')
    const section = screen.getByRole('region', { name: 'Import past pull requests' })
    expect(await within(section).findByText(/has no GITHUB_TOKEN/)).toBeInTheDocument()
    fillRepo(section)
    fireEvent.change(within(section).getByLabelText('Updated since (optional)'), { target: { value: '2026-09-01' } })
    fireEvent.click(within(section).getByRole('button', { name: 'Import' }))

    const result = await within(section).findByRole('status')
    expect(result).toHaveTextContent('3 recorded, 1 already recorded or excluded.')
    expect(result).toHaveTextContent('#7: diff too large')
    const call = fetch.mock.calls.find(([url]) => url.includes('/backfill'))!
    expect(JSON.parse(String(call[1]!.body))).toEqual({
      company_id: 4, owner: 'acme', repo: 'app', since: '2026-09-01T00:00:00.000Z',
    })
  })

  it('asks to connect a repository before importing it', async () => {
    stubApi({ '/v1/integrations/github/backfill': [() => response(404, { detail: 'not bound' })] })
    renderAs('Manager')
    const section = screen.getByRole('region', { name: 'Import past pull requests' })
    fillRepo(section)
    fireEvent.click(within(section).getByRole('button', { name: 'Import' }))
    expect(await within(section).findByRole('alert')).toHaveTextContent('Connect that repository first.')
  })
})
