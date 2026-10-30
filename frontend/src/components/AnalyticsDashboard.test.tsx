import { render, screen, within } from '@testing-library/react'
import i18n from 'i18next'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsDashboard } from './AnalyticsDashboard'
import { useAnalyticsSummary, useOrchestrationHealth } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'

vi.mock('../hooks/useQueries', () => ({
  useAnalyticsSummary: vi.fn(),
  useOrchestrationHealth: vi.fn(),
  useSprintBoard: vi.fn(),
}))

const mockedUseAnalyticsSummary = vi.mocked(useAnalyticsSummary)
const mockedUseOrchestrationHealth = vi.mocked(useOrchestrationHealth)

function getCard(label: string) {
  const card = screen.getByText(label).closest('.card') as HTMLElement | null
  expect(card).not.toBeNull()
  return card!
}

const analyticsSummary = {
  health_score: 88,
  tokens_consumed: 45678,
  tasks_completed: 7,
  tasks_failed: 1,
  tasks_in_progress: 2,
  agent_breakdown: [],
  executive_summary: '',
}

const orchestrationHealth = {
  anchor_commit: 'abc1234',
  anchor_date: '2026-04-01',
  weeks: [
    {
      week: '2026-W12',
      qa_needs_work_rate: 0.32,
      avg_developer_tokens: 1234.5,
      architect_consult_count: 4,
      task_count: 10,
      post_batch1: false,
    },
    {
      week: '2026-W16',
      qa_needs_work_rate: 0.125,
      avg_developer_tokens: 9876.4,
      architect_consult_count: 3,
      task_count: 8,
      post_batch1: true,
    },
    {
      week: '2026-W17',
      qa_needs_work_rate: 0.25,
      avg_developer_tokens: 8765.2,
      architect_consult_count: 6,
      task_count: 9,
      post_batch1: true,
    },
  ],
  summary: {
    pre_batch1: {
      qa_needs_work_rate: 0.32,
      avg_developer_tokens: 1234.5,
    },
    post_batch1: {
      qa_needs_work_rate: 0.125,
      avg_developer_tokens: 9876.4,
    },
  },
}

type AnalyticsSummaryHookResult = {
  data?: typeof analyticsSummary
  isLoading: boolean
  isError: boolean
  refetch: ReturnType<typeof vi.fn>
}

type OrchestrationHealthHookResult = {
  data?: typeof orchestrationHealth
  isLoading: boolean
  isError: boolean
  refetch: ReturnType<typeof vi.fn>
}

function mockAnalyticsSummary(overrides: Partial<AnalyticsSummaryHookResult> = {}) {
  mockedUseAnalyticsSummary.mockReturnValue({
    data: analyticsSummary,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as never)
}

function mockOrchestrationHealth(overrides: Partial<OrchestrationHealthHookResult> = {}) {
  mockedUseOrchestrationHealth.mockReturnValue({
    data: orchestrationHealth,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as never)
}

describe('AnalyticsDashboard orchestration health', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({
      companyId: 42,
      companyName: 'Le Fabrique',
      activeSprintId: 9,
    })
  })

  it('renders KPI values, period summaries, and pre/post batch chart weeks', () => {
    mockAnalyticsSummary()
    mockOrchestrationHealth()

    const { container } = render(<AnalyticsDashboard sprintId={9} />)

    const qaRateCard = getCard(i18n.t('analytics.orchestration_health.qa_rate'))
    const avgTokensCard = getCard(i18n.t('analytics.orchestration_health.avg_tokens'))
    const consultCard = getCard(i18n.t('analytics.orchestration_health.consult_freq'))

    expect(within(qaRateCard).getByText(i18n.t('analytics.orchestration_health.pre_batch1'))).toBeInTheDocument()
    expect(within(qaRateCard).getByText(i18n.t('analytics.orchestration_health.post_batch1'))).toBeInTheDocument()
    expect(within(qaRateCard).getByText('32.0%')).toBeInTheDocument()
    expect(within(qaRateCard).getByText('12.5%')).toBeInTheDocument()
    expect(within(qaRateCard).queryByText('0.32%')).not.toBeInTheDocument()

    expect(within(avgTokensCard).getByText('1,235')).toBeInTheDocument()
    expect(within(avgTokensCard).getByText('9,876')).toBeInTheDocument()
    expect(within(consultCard).getByText('9')).toBeInTheDocument()

    expect(screen.getByText(`(${i18n.t('analytics.orchestration_health.anchor_date')}: 2026-04-01)`)).toBeInTheDocument()

    expect(container.querySelectorAll('rect[fill="#818cf8"]')).toHaveLength(1)
    expect(container.querySelectorAll('rect[fill="#22d3ee"]')).toHaveLength(2)
  })

  it('says how many Developer turns had no reported token count, and only when some did', () => {
    mockAnalyticsSummary()
    mockOrchestrationHealth({
      data: {
        ...orchestrationHealth,
        weeks: orchestrationHealth.weeks.map((week, index) => ({ ...week, developer_turns_without_tokens: index })),
      },
    })
    const { unmount } = render(<AnalyticsDashboard sprintId={9} />)
    const avgTokensCard = getCard(i18n.t('analytics.orchestration_health.avg_tokens'))
    expect(within(avgTokensCard).getByText(i18n.t('analytics.orchestration_health.tokens_unreported', { count: 3 }))).toBeInTheDocument()
    unmount()

    mockOrchestrationHealth()
    render(<AnalyticsDashboard sprintId={9} />)
    expect(screen.queryByText(/no reported token count/)).not.toBeInTheDocument()
  })

  it('renders the empty state without NaN values or chart bars when no weeks are returned', () => {
    mockAnalyticsSummary()
    mockOrchestrationHealth({
      data: {
        ...orchestrationHealth,
        weeks: [],
      },
    })

    const { container } = render(<AnalyticsDashboard sprintId={9} />)

    expect(screen.getByText(i18n.t('analytics.orchestration_health.empty'))).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(container.querySelectorAll('rect[fill="#818cf8"], rect[fill="#22d3ee"]')).toHaveLength(0)
  })

  it('renders loading placeholders while orchestration health is loading', () => {
    mockAnalyticsSummary()
    mockOrchestrationHealth({
      data: undefined,
      isLoading: true,
    })

    const { container } = render(<AnalyticsDashboard sprintId={9} />)

    expect(container.querySelectorAll('.skeleton')).toHaveLength(4)
  })

  it('renders the orchestration health error state', () => {
    mockAnalyticsSummary()
    mockOrchestrationHealth({
      data: undefined,
      isError: true,
    })

    render(<AnalyticsDashboard sprintId={9} />)

    expect(screen.getByText(i18n.t('analytics.error'))).toBeInTheDocument()
  })
})
