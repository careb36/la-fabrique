import { fireEvent, render, screen } from '@testing-library/react'
import i18n from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Evidence from './Evidence'
import { useAgentRuns } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import type { AgentRunListItem } from '../services/api'
import es from '../i18n/es.json'

vi.mock('../hooks/useQueries', () => ({
  useAgentRuns: vi.fn(),
}))

const mockedUseAgentRuns = vi.mocked(useAgentRuns)

const runs: AgentRunListItem[] = (['verified', 'refuted', 'unverifiable', 'ingested'] as const).map((status, index) => ({
  id: index + 1,
  company_id: 42,
  external_ref: `run-${status}`,
  version: 1,
  producer: 'test-agent',
  model: null,
  agent_role: null,
  subject: null,
  claims: null,
  artifact_digest: 'digest',
  artifact_size: 0,
  status,
  started_at: null,
  finished_at: null,
  ingested_at: '2026-10-15T12:00:00Z',
  audit_log_id: null,
  latest_approval: null,
}))

function mockRuns(overrides: Record<string, unknown> = {}) {
  mockedUseAgentRuns.mockReturnValue({
    data: { agent_runs: runs },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as never)
}

describe('Evidence list', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    void i18n.changeLanguage('en')
    useAppStore.setState({ companyId: 42, companyName: 'Example', activeSprintId: null })
  })

  it('renders all verdicts with distinct labels, icons, and styles', () => {
    mockRuns()
    const { container } = render(<MemoryRouter><Evidence /></MemoryRouter>)

    for (const status of ['verified', 'refuted', 'unverifiable', 'ingested'] as const) {
      expect(screen.getByTestId(`verdict-${status}`)).toHaveTextContent(i18n.t(`evidence.verdict.${status}`))
      expect(screen.getByTestId(`verdict-icon-${status}`)).toBeInTheDocument()
    }
    const verdictClasses = runs.map(run => screen.getByTestId(`verdict-${run.status}`).className)
    expect(new Set(verdictClasses).size).toBe(4)
    expect(container.querySelectorAll('[data-testid^="verdict-icon-"]')).toHaveLength(4)
  })

  it('renders the loading state', () => {
    mockRuns({ data: undefined, isLoading: true })
    render(<MemoryRouter><Evidence /></MemoryRouter>)
    expect(screen.getByRole('status', { name: i18n.t('evidence.loading') })).toBeInTheDocument()
  })

  it('renders the error state', () => {
    mockRuns({ data: undefined, isError: true })
    render(<MemoryRouter><Evidence /></MemoryRouter>)
    expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('evidence.error'))
  })

  it('renders the empty state', () => {
    mockRuns({ data: { agent_runs: [] } })
    render(<MemoryRouter><Evidence /></MemoryRouter>)
    expect(screen.getByText(i18n.t('evidence.empty'))).toBeInTheDocument()
  })

  it('shows a company selection state without calling the runs hook without a company', () => {
    useAppStore.setState({ companyId: null, companyName: null, activeSprintId: null })
    render(<Evidence />)
    expect(screen.getByText(i18n.t('evidence.selectCompany'))).toBeInTheDocument()
    expect(mockedUseAgentRuns).not.toHaveBeenCalled()
  })

  it('renders the verdict labels from the Spanish locale', async () => {
    i18n.addResourceBundle('es', 'translation', es, true, true)
    await i18n.changeLanguage('es')
    mockRuns()
    render(<MemoryRouter><Evidence /></MemoryRouter>)

    expect(screen.getByTestId('verdict-verified')).toHaveTextContent('Verificado')
    expect(screen.getByTestId('verdict-refuted')).toHaveTextContent('Refutado')
    expect(screen.getByTestId('verdict-unverifiable')).toHaveTextContent('No verificable')
    expect(screen.getByTestId('verdict-ingested')).toHaveTextContent('Aún sin verificar')
  })

  it('chunks the runs by verdict with a count per status', () => {
    mockRuns()
    render(<MemoryRouter><Evidence /></MemoryRouter>)

    expect(screen.getByTestId('summary-all')).toHaveTextContent('4')
    expect(screen.getByTestId('summary-verified')).toHaveTextContent('1')
    expect(screen.getByTestId('summary-refuted')).toHaveTextContent('1')
    expect(screen.getByTestId('summary-unverifiable')).toHaveTextContent('1')
    expect(screen.getByTestId('summary-ingested')).toHaveTextContent('1')
  })

  it('filters the list to one verdict and reports the narrowed count', () => {
    mockRuns()
    render(<MemoryRouter><Evidence /></MemoryRouter>)

    fireEvent.click(screen.getByTestId('summary-refuted'))

    expect(screen.getByTestId('verdict-refuted')).toBeInTheDocument()
    expect(screen.queryByTestId('verdict-verified')).not.toBeInTheDocument()
    expect(screen.queryByTestId('verdict-unverifiable')).not.toBeInTheDocument()
    expect(screen.queryByTestId('verdict-ingested')).not.toBeInTheDocument()
    expect(screen.getByText(/Showing 1 of 4 runs/)).toBeInTheDocument()
  })

  it('shows a clear-filters action while a filter is active and resets it', () => {
    mockRuns()
    render(<MemoryRouter><Evidence /></MemoryRouter>)

    expect(screen.queryByRole('button', { name: /Clear filters/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('summary-refuted'))
    const clear = screen.getByRole('button', { name: /Clear filters/ })
    expect(clear).toBeInTheDocument()

    fireEvent.click(clear)
    expect(screen.queryByTestId('verdict-verified')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Clear filters/ })).not.toBeInTheDocument()
  })

  it('makes the whole row a link to the run detail', () => {
    mockRuns()
    render(<MemoryRouter><Evidence /></MemoryRouter>)

    const links = screen.getAllByRole('link', { name: /run-verified/ })
    expect(links.length).toBeGreaterThan(0)
    expect(links[0]).toHaveAttribute('href', '/evidence/1')
  })
})
