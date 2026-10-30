import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GovernancePanel } from './GovernancePanel'
import { useAgentRuns, useCurrentRole, useInbox, useReviewerRecord, useSprints, useUpdateBacklogItem } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'

vi.mock('../hooks/useQueries', () => ({
  useAgentRuns: vi.fn(),
  useCurrentRole: vi.fn(),
  useInbox: vi.fn(),
  useReviewerRecord: vi.fn(),
  useSprints: vi.fn(),
  useUpdateBacklogItem: vi.fn(),
}))

const mockedUseAgentRuns = vi.mocked(useAgentRuns)
const mockedUseCurrentRole = vi.mocked(useCurrentRole)
const mockedUseInbox = vi.mocked(useInbox)
const mockedUseReviewerRecord = vi.mocked(useReviewerRecord)
const mockedUseSprints = vi.mocked(useSprints)
const mockedUseUpdateBacklogItem = vi.mocked(useUpdateBacklogItem)

const INBOX = {
  blocked_tasks: [
    {
      id: 7, title: 'Create testing strategy document', assignee: 'QA', sprint_id: 1, sprint_name: 'Sprint 0 — Foundations',
      sprint_status: 'completed', reason: 'Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: Too short',
      triage: { decision: 'retry', why: 'The attempts were cut short, not wrong.', brief: 'Write at least 180 words with a section per test level.' },
      frozen: false, updated_at: '2026-10-19T04:39:00',
    },
    {
      id: 8, title: 'Frozen one', assignee: 'Developer', sprint_id: 1, sprint_name: 'Sprint 0 — Foundations',
      sprint_status: 'completed', reason: 'freeze after sleep-induced churn', triage: null, frozen: true, updated_at: null,
    },
  ],
  proposals: [{ id: 3, role: 'Developer', title: 'Cover edge cases', proposed_by: 'ScrumMaster', source_sprint_id: 1, created_at: null }],
  pending_runs: 1,
  total: 4,
}

describe('GovernancePanel', () => {
  const mutate = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ companyId: 42, companyName: 'Example', activeSprintId: null })
    mockedUseAgentRuns.mockReturnValue({
      data: {
        agent_runs: [
          { id: 1, external_ref: 'needs-review', producer: 'producer-a', agent_role: 'Developer', latest_approval: null },
          { id: 2, external_ref: 'already-reviewed', producer: 'producer-b', agent_role: 'QA', latest_approval: { decision: 'approved' } },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    mockedUseInbox.mockReturnValue({ data: INBOX, isLoading: false, isError: false, refetch: vi.fn() } as never)
    mockedUseReviewerRecord.mockReturnValue({ data: undefined } as never)
    mockedUseCurrentRole.mockReturnValue('Manager')
    mockedUseSprints.mockReturnValue({ data: [] } as never)
    mockedUseUpdateBacklogItem.mockReturnValue({ mutate, isPending: false, isError: false, error: null } as never)
  })

  it('lists only runs without a latest approval and links to their evidence', () => {
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    expect(screen.getByText('needs-review')).toBeInTheDocument()
    expect(screen.queryByText('already-reviewed')).not.toBeInTheDocument()
    // The company's own deliveries and kickoff transcripts are decided by the
    // review loop: the page asks the server to leave them out.
    expect(mockedUseAgentRuns).toHaveBeenCalledWith(42, { limit: 500, exclude_in_house: true })
    expect(screen.getByRole('link', { name: /Review evidence/ })).toHaveAttribute('href', '/evidence/1')
    expect(screen.getByRole('heading', { name: 'Review' })).toBeInTheDocument()
  })

  it("shows the Reviewer agent's suggestion beside a run, and its record against the decisions", () => {
    mockedUseAgentRuns.mockReturnValue({
      data: {
        agent_runs: [
          {
            id: 1, external_ref: 'needs-review', producer: 'producer-a', agent_role: 'Developer', latest_approval: null,
            reviewed_by: 'Reviewer agent', suggested_decision: 'rejected', suggested_category: 'quality', suggested_reason: 'The suite exited 1.',
          },
          { id: 3, external_ref: 'left-to-people', producer: 'producer-c', agent_role: null, latest_approval: null, reviewed_by: 'Reviewer agent', suggested_decision: null },
          { id: 4, external_ref: 'not-yet-reviewed', producer: 'producer-d', agent_role: null, latest_approval: null },
        ],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    mockedUseReviewerRecord.mockReturnValue({
      data: { decided: 4, agent_agreed: 3, agent_unusable: 1, verifier_called: 2, verifier_agreed: 2 },
    } as never)
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    expect(mockedUseReviewerRecord).toHaveBeenCalledWith(42)
    expect(screen.getByRole('note')).toHaveTextContent(
      "The Reviewer agent's suggestion matched 3 of 4 decisions (1 without a usable answer); the Verifier's verdict alone 2 of the 2 it called.",
    )
    const reviewed = screen.getByText('needs-review').closest('article') as HTMLElement
    expect(within(reviewed).getByText('Reviewer agent suggests: Rejected')).toBeInTheDocument()
    const unusable = screen.getByText('left-to-people').closest('article') as HTMLElement
    expect(within(unusable).getByText('The Reviewer agent could not suggest a decision; it is left to people.')).toBeInTheDocument()
    const pending = screen.getByText('not-yet-reviewed').closest('article') as HTMLElement
    expect(within(pending).queryByText(/Reviewer agent/)).not.toBeInTheDocument()
  })

  it('shows the tasks blocked for a person with their reason, and a Manager can send one back', () => {
    const sprint = (id: number, status: string, second_attempts: object) => ({
      id, sprint_name: `S${id}`, status, goal: null, start_date: null, scope_size: 'S', total: 4, done: 3, blocked: 1, rework: 2, second_attempts, console_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } }, architect_advice: { advised: { total: 0, done: 0, rework: 0 }, unadvised: { total: 0, done: 0, rework: 0 } },
    })
    mockedUseSprints.mockReturnValue({
      data: [
        // Still open: its second attempts have no outcome yet.
        sprint(4, 'active', { total: 2, done: 0, briefed: 2, briefed_done: 0 }),
        sprint(3, 'completed', { total: 3, done: 2, briefed: 2, briefed_done: 2 }),
      ],
    } as never)
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    const blocked = screen.getByRole('region', { name: /Tasks blocked until someone acts/ })
    // What earlier second attempts did, from the closed sprints' boards, beside the advice.
    expect(mockedUseSprints).toHaveBeenCalledWith(42)
    expect(within(blocked).getByText("So far 2 of 3 second attempts got done; with the ScrumMaster's brief, 2 of 2.")).toBeInTheDocument()
    expect(within(blocked).getByRole('link', { name: 'Create testing strategy document' })).toHaveAttribute('href', '/sprints/1/tasks/7')
    expect(within(blocked).getByText(/blocked for manual triage: Too short/)).toBeInTheDocument()
    expect(within(blocked).getByText(/frozen by an operator/)).toBeInTheDocument()
    // The ScrumMaster's answer to the escalation sits under the reason, as its claim.
    const triage = within(blocked).getByText(/ScrumMaster: another attempt in the next sprint\./)
    expect(triage.closest('p')).toHaveTextContent('The attempts were cut short, not wrong. Brief: Write at least 180 words with a section per test level.')
    expect(within(blocked).queryByText(/leave it for a person/)).not.toBeInTheDocument()
    // Only the task the agents gave up on gets the button; a frozen one is the operator's.
    const buttons = within(blocked).getAllByRole('button', { name: 'Send back to work' })
    expect(buttons).toHaveLength(1)

    fireEvent.click(buttons[0])

    expect(mutate).toHaveBeenCalledWith({ itemId: 7, data: { status: 'todo', comment: 'Sent back to work by a person.' } })
  })

  it('lets a Manager accept an approved high-risk delivery, or send it back', () => {
    mockedUseInbox.mockReturnValue({
      data: {
        ...INBOX,
        blocked_tasks: [{
          id: 9, title: 'Rework login', assignee: 'Developer', sprint_id: 2, sprint_name: 'S2', sprint_status: 'active',
          reason: 'High-risk delivery approved by QA, waiting for a person to accept it (authentication: app/auth.py).',
          triage: null, frozen: false, risk_hold: true, updated_at: null,
        }],
      },
      isLoading: false, isError: false, refetch: vi.fn(),
    } as never)
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    const blocked = screen.getByRole('region', { name: /Tasks blocked until someone acts/ })
    expect(within(blocked).getByText('Approved by QA, but high risk: a person accepts it or sends it back.')).toBeInTheDocument()
    expect(within(blocked).getByRole('button', { name: 'Send back to work' })).toBeInTheDocument()

    fireEvent.click(within(blocked).getByRole('button', { name: 'Accept' }))

    expect(mutate).toHaveBeenCalledWith({ itemId: 9, data: { status: 'done', comment: 'High-risk delivery accepted by a person.' } })
  })

  it('offers Accept only on a high-risk hold', () => {
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('links proposals to the procedures page and counts undecided runs', () => {
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    const proposals = screen.getByRole('region', { name: /Procedure proposals waiting for a decision/ })
    expect(within(proposals).getByText('Cover edge cases')).toBeInTheDocument()
    expect(within(proposals).getByText('Developer · proposed by ScrumMaster')).toBeInTheDocument()
    expect(within(proposals).getByRole('link', { name: 'Decide' })).toHaveAttribute('href', '/company/procedures')
    expect(screen.getByRole('heading', { name: /Runs awaiting a decision/ })).toHaveTextContent('1')
  })

  it('offers no action to a Viewer and says so when nothing waits', () => {
    mockedUseCurrentRole.mockReturnValue('Viewer')
    mockedUseInbox.mockReturnValue({
      data: { blocked_tasks: [], proposals: [], pending_runs: 0, total: 0 }, isLoading: false, isError: false, refetch: vi.fn(),
    } as never)
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    expect(screen.queryByRole('button', { name: 'Send back to work' })).not.toBeInTheDocument()
    // Nothing to decide on, so the sprint list is not fetched.
    expect(mockedUseSprints).toHaveBeenCalledWith(null)
    expect(screen.getByText('No task is waiting for a person.')).toBeInTheDocument()
    expect(screen.getByText('No proposal is waiting.')).toBeInTheDocument()
  })

  it('reports a load error with a refresh button', () => {
    const refetch = vi.fn()
    mockedUseInbox.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: new Error('boom'), refetch } as never)
    render(<MemoryRouter><GovernancePanel /></MemoryRouter>)

    expect(screen.getByRole('alert')).toHaveTextContent(/Could not load what needs you/)
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button'))
    expect(refetch).toHaveBeenCalled()
  })
})
