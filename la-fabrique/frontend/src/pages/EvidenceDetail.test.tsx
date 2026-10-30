import { fireEvent, render, screen, within } from '@testing-library/react'
import i18n from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EvidenceDetail from './EvidenceDetail'
import {
  useAgentRun,
  useAgentRunApprovals,
  useAgentRunVerifications,
  useApproveAgentRun,
  useAuditVerification,
  useVerifyAgentRun,
} from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import { ApiError } from '../services/api'

vi.mock('../hooks/useQueries', () => ({
  useAgentRun: vi.fn(),
  useAgentRunApprovals: vi.fn(),
  useAgentRunVerifications: vi.fn(),
  useApproveAgentRun: vi.fn(),
  useAuditVerification: vi.fn(),
  useVerifyAgentRun: vi.fn(),
}))

const mockedUseAgentRun = vi.mocked(useAgentRun)
const mockedUseAgentRunApprovals = vi.mocked(useAgentRunApprovals)
const mockedUseAgentRunVerifications = vi.mocked(useAgentRunVerifications)
const mockedUseApproveAgentRun = vi.mocked(useApproveAgentRun)
const mockedUseAuditVerification = vi.mocked(useAuditVerification)
const mockedUseVerifyAgentRun = vi.mocked(useVerifyAgentRun)
const approveMutation = vi.fn()

function setup(id = '7') {
  return render(
    <MemoryRouter initialEntries={[`/evidence/${id}`]}>
      <Routes><Route path="/evidence/:runId" element={<EvidenceDetail />} /></Routes>
    </MemoryRouter>,
  )
}

const RUN = {
  id: 7,
  company_id: 42,
  external_ref: 'issue-27-run',
  version: 1,
  producer: 'github',
  model: null,
  agent_role: 'Developer',
  subject: null,
  claims: { title: 'Adds backend/app/crypto.py with Fernet encryption', summary: 'Crypto implementation added' },
  artifact_text: '',
  artifact_digest: 'digest',
  artifact_size: 0,
  status: 'refuted',
  started_at: null,
  finished_at: null,
  ingested_at: '2026-10-15T12:00:00Z',
  audit_log_id: 10,
  latest_approval: null,
}

describe('Evidence detail', () => {
  it.each(['bad', '7x', '0', '-1', '1.5', '9007199254740992'])('rejects malformed run ID %s without querying', id => {
    setup(id)
    expect(screen.getByRole('alert')).toHaveTextContent(`Invalid run ID: ${id}`)
    expect(mockedUseAgentRun).not.toHaveBeenCalled()
  })

  it('names a run that was not found', () => {
    mockedUseAgentRun.mockReturnValue({ isError: true, error: new ApiError(404, 'missing') } as never)
    setup()
    expect(screen.getByRole('alert')).toHaveTextContent('Run #7 was not found')
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to evidence' })).toHaveAttribute('href', '/evidence')
  })

  it('names a run that failed to load and offers Retry', () => {
    const refetch = vi.fn()
    mockedUseAgentRun.mockReturnValue({ isError: true, error: new ApiError(503, 'failed'), refetch } as never)
    setup()
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load run #7')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetch).toHaveBeenCalledOnce()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    void i18n.changeLanguage('en')
    useAppStore.setState({ companyId: 42, companyName: 'Example', activeSprintId: null })
    mockedUseAgentRun.mockReturnValue({ data: RUN, isLoading: false, isError: false } as never)
    mockedUseAgentRunVerifications.mockReturnValue({
      data: {
        verifications: [{
          id: 2,
          verdict: 'refuted',
          checks: [{
            name: 'artifact_nonempty',
            outcome: 'refuted',
            observation: 'claims present but artifact is empty (0 bytes)',
          }],
          evidence: null,
          observed_at: '2026-10-15T12:30:00Z',
          audit_log_id: 11,
        }],
      },
      isLoading: false,
      isError: false,
    } as never)
    mockedUseAgentRunApprovals.mockReturnValue({
      data: { approvals: [] },
      isLoading: false,
      isError: false,
    } as never)
    mockedUseAuditVerification.mockReturnValue({
      data: {
        interaction_id: 'agent-run:issue-27-run',
        summary: { valid: 0, invalid: 0, unsigned: 1, legacy: 1 },
        rows: [
          { id: 10, action: 'agent_run_ingested', status: 'unsigned', mode: 'unsigned' },
          { id: 11, action: 'agent_run_verified', status: 'legacy', mode: 'legacy' },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
    } as never)
    mockedUseVerifyAgentRun.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as never)
    mockedUseApproveAgentRun.mockReturnValue({
      mutate: approveMutation,
      isPending: false,
      isError: false,
      isSuccess: false,
    } as never)
  })

  it('shows a claim beside the concrete observation', () => {
    setup()
    expect(mockedUseAuditVerification).toHaveBeenCalledWith('issue-27-run', 42)
    expect(screen.getByText('Adds backend/app/crypto.py with Fernet encryption')).toBeInTheDocument()
    const observedPanel = screen.getByText(i18n.t('evidence.observed')).closest('.card') as HTMLElement
    expect(within(observedPanel).getByText('claims present but artifact is empty (0 bytes)')).toBeInTheDocument()
    expect(screen.getByText('artifact_nonempty')).toBeInTheDocument()
  })

  it("shows the Reviewer agent's suggestion as a claim beside the review form", () => {
    mockedUseAgentRun.mockReturnValue({
      data: {
        ...RUN, reviewed_by: 'Reviewer agent', reviewed_at: '2026-10-15T13:00:00Z',
        suggested_decision: 'rejected', suggested_category: 'quality', suggested_reason: 'The artifact is empty while the claims name a file.',
      },
      isLoading: false,
      isError: false,
    } as never)
    setup()

    const aside = screen.getByRole('complementary', { name: "The Reviewer agent's suggestion" })
    expect(aside).toHaveTextContent('Reviewer agent')
    expect(aside).toHaveTextContent('Rejected · Quality')
    expect(aside).toHaveTextContent('The artifact is empty while the claims name a file.')
    expect(aside).toHaveTextContent('never a decision: the review below is yours')
    // The form starts from the person's own default, not from the suggestion.
    expect(screen.getByRole('combobox', { name: /Decision/ })).toHaveValue('approved')
  })

  it('says when the Reviewer agent could not suggest, and shows nothing before it looked', () => {
    setup()
    expect(screen.queryByRole('complementary', { name: "The Reviewer agent's suggestion" })).not.toBeInTheDocument()

    mockedUseAgentRun.mockReturnValue({
      data: { ...RUN, reviewed_by: 'Reviewer agent', reviewed_at: '2026-10-15T13:00:00Z', suggested_decision: null },
      isLoading: false,
      isError: false,
    } as never)
    setup()
    expect(screen.getByRole('complementary', { name: "The Reviewer agent's suggestion" }))
      .toHaveTextContent('The Reviewer agent could not suggest a decision; it is left to people.')
  })

  it('shows an Evidence › Run breadcrumb instead of a back link', () => {
    setup()
    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(breadcrumb).getAllByRole('listitem').map(item => item.textContent)).toEqual(['Evidence', 'Run #7'])
    expect(within(breadcrumb).getByRole('link', { name: 'Evidence' })).toHaveAttribute('href', '/evidence')
    expect(within(breadcrumb).queryByRole('link', { name: 'Run #7' })).not.toBeInTheDocument()
    expect(document.querySelector('[aria-current]')).toBeNull()
    expect(screen.queryByRole('link', { name: 'Back to evidence' })).not.toBeInTheDocument()
  })

  it('renders unsigned and legacy audit rows without the valid style', () => {
    setup()
    const unsigned = screen.getByTestId('signature-row-unsigned')
    const legacy = screen.getByTestId('signature-row-legacy')
    expect(unsigned).toHaveTextContent(i18n.t('evidence.signature.unsigned'))
    expect(legacy).toHaveTextContent(i18n.t('evidence.signature.legacy'))
    expect(unsigned.className).not.toContain('emerald')
    expect(legacy.className).not.toContain('emerald')
    expect(screen.getByTestId('signature-unsigned')).toHaveTextContent('1')
    expect(screen.getByTestId('signature-legacy')).toHaveTextContent('1')
  })

  it('does not submit a rejection with blank feedback and shows validation', () => {
    setup()
    fireEvent.change(screen.getByLabelText(i18n.t('evidence.approverName')), { target: { value: 'Reviewer' } })
    fireEvent.change(screen.getByLabelText(i18n.t('evidence.decision')), { target: { value: 'rejected' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('evidence.submitReview') }))

    expect(approveMutation).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(i18n.t('evidence.feedbackRequired'))
  })

  it('flags legacy company ownership separately from signature verification', () => {
    mockedUseAuditVerification.mockReturnValue({
      data: {
        interaction_id: 'agent-run:issue-27-run',
        summary: { valid: 1, invalid: 0, unsigned: 0, legacy: 0 },
        rows: [{ id: 10, action: 'old', status: 'valid', mode: 'hmac-sha256', company_id: null, legacy: true }],
      },
      isLoading: false,
      isError: false,
      error: null,
    } as never)
    setup()
    expect(screen.getByTestId('legacy-company')).toHaveTextContent(i18n.t('evidence.legacyCompany'))
    expect(screen.getByTestId('legacy-company').className).not.toContain('emerald')
    expect(screen.getByTestId('signature-row-valid')).toBeInTheDocument()
  })

  it('links a task-worker run back to the task it delivered', () => {
    // The run set up in beforeEach, from the producer 'github'.
    const base = mockedUseAgentRun(42, 7) as unknown as { data: Record<string, unknown> }
    mockedUseAgentRun.mockReturnValue({
      ...base,
      data: {
        ...base.data,
        external_ref: 'task-2',
        producer: 'le-fabrique-task-worker',
        subject: { sprint_id: 7, backlog_item_id: 2, title: 'Encrypt credentials' },
      },
    } as never)
    setup()
    const link = screen.getByRole('link', { name: 'Encrypt credentials' })
    expect(link).toHaveAttribute('href', '/sprints/7/tasks/2')
    expect(link.closest('p')).toHaveTextContent('Task: Encrypt credentials')
  })

  it('offers no task link for a run from another producer, even with a task-shaped subject', () => {
    // The run set up in beforeEach, from the producer 'github'.
    const base = mockedUseAgentRun(42, 7) as unknown as { data: Record<string, unknown> }
    mockedUseAgentRun.mockReturnValue({
      ...base,
      data: { ...base.data, subject: { sprint_id: 7, backlog_item_id: 2, title: 'Encrypt credentials' } },
    } as never)
    setup()
    expect(screen.queryByRole('link', { name: 'Encrypt credentials' })).not.toBeInTheDocument()
    expect(document.querySelector('a[href^="/sprints/"]')).toBeNull()
  })

  it('submits the exact rejection body when feedback is provided', () => {
    setup()
    fireEvent.change(screen.getByLabelText(i18n.t('evidence.approverName')), { target: { value: ' Reviewer ' } })
    fireEvent.change(screen.getByLabelText(i18n.t('evidence.decision')), { target: { value: 'rejected' } })
    fireEvent.change(screen.getByLabelText(`${i18n.t('evidence.feedback')} *`), { target: { value: '  Missing artifact  ' } })
    fireEvent.change(screen.getByLabelText(i18n.t('evidence.rejectionCategory')), { target: { value: 'security' } })
    fireEvent.click(screen.getByRole('button', { name: i18n.t('evidence.submitReview') }))

    expect(approveMutation).toHaveBeenCalledWith({
      company_id: 42,
      approver_name: 'Reviewer',
      decision: 'rejected',
      feedback: 'Missing artifact',
      rejection_category: 'security',
    })
  })
})
