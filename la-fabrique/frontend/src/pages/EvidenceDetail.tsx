import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react'
import { Breadcrumbs } from '../components/Breadcrumbs'
import { ApiError, type AgentRunStatus } from '../services/api'
import {
  useAgentRun,
  useAgentRunApprovals,
  useAgentRunVerifications,
  useApproveAgentRun,
  useAuditVerification,
  useVerifyAgentRun,
} from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import { Verdict } from '../components/Verdict'
import { parseRouteId } from '../lib/routeId'
import { taskOfRun } from '../lib/taskEvidence'

function claimValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return String(value)
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const SIGNATURE_STYLES = {
  valid: 'text-emerald-300 bg-emerald-950/60 border-emerald-700/50',
  invalid: 'text-red-300 bg-red-950/60 border-red-700/50',
  unsigned: 'text-amber-300 bg-amber-950/60 border-amber-700/50',
  legacy: 'text-gray-300 bg-gray-800 border-gray-600',
} as const

function RunDetail({ companyId, runId }: { companyId: number; runId: number }) {
  const { t } = useTranslation()
  const runQuery = useAgentRun(companyId, runId)
  const verificationsQuery = useAgentRunVerifications(companyId, runId)
  const approvalsQuery = useAgentRunApprovals(companyId, runId)
  const run = runQuery.data
  const externalRef = run?.external_ref ?? null
  const auditQuery = useAuditVerification(externalRef, companyId)
  const verifyMutation = useVerifyAgentRun(companyId, runId)
  const approveMutation = useApproveAgentRun(companyId, runId)
  const [approverName, setApproverName] = useState('')
  const [decision, setDecision] = useState<'approved' | 'rejected'>('approved')
  const [feedback, setFeedback] = useState('')
  const [category, setCategory] = useState('')
  const [formError, setFormError] = useState('')

  const verifications = verificationsQuery.data?.verifications ?? []
  const latestVerification = verifications[verifications.length - 1]
  const audit = auditQuery.data

  function submitApproval(event: React.FormEvent) {
    event.preventDefault()
    if (decision === 'rejected' && !feedback.trim()) {
      setFormError(t('evidence.feedbackRequired'))
      return
    }
    if (!approverName.trim()) {
      setFormError(t('evidence.approverRequired'))
      return
    }
    setFormError('')
    approveMutation.mutate({
      company_id: companyId,
      approver_name: approverName.trim(),
      decision,
      ...(feedback.trim() ? { feedback: feedback.trim() } : {}),
      ...(decision === 'rejected' && category ? { rejection_category: category as 'scope' | 'quality' | 'security' | 'other' } : {}),
    })
  }

  if (runQuery.isLoading) {
    return <div role="status" className="skeleton h-48 rounded-lg" aria-label={t('evidence.loading')} />
  }
  if (runQuery.isError || !run) {
    const notFound = runQuery.error instanceof ApiError && runQuery.error.status === 404
    return (
      <div className="space-y-4">
        <div role="alert" className="alert-error">{t(notFound ? 'evidence.notFound' : 'evidence.loadError', { id: runId })}</div>
        {!notFound && <button onClick={() => runQuery.refetch()} className="btn btn-ghost mr-3">{t('common.retry')}</button>}
        <Link to="/evidence" className="btn btn-ghost">{t('evidence.backToRuns')}</Link>
      </div>
    )
  }

  const verdict: AgentRunStatus = latestVerification?.verdict ?? run.status
  const task = taskOfRun(run)

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[
        { label: t('nav.evidence', { defaultValue: 'Evidence' }), to: '/evidence' },
        { label: t('evidence.runCrumb', { id: runId, defaultValue: 'Run #{{id}}' }) },
      ]} />
      <header className="page-header">
        <h1 className="page-title">{t('evidence.detailTitle')}</h1>
        <div className="min-w-0 sm:text-right">
          <p className="mt-1 break-all font-mono text-sm text-gray-400">{run.external_ref} · {run.producer}</p>
          {task && (
            <p className="mt-1 text-sm text-gray-400">
              {t('evidence.taskLabel', { defaultValue: 'Task' })}:{' '}
              <Link to={task.to} className="break-words font-medium text-brand-300 hover:underline">
                {task.title ?? t('evidence.taskFallback', { id: task.itemId, defaultValue: 'Task #{{id}}' })}
              </Link>
            </p>
          )}
        </div>
      </header>

      <section aria-labelledby="claim-observation-title">
        <h2 id="claim-observation-title" className="mb-3 text-lg font-semibold text-white">{t('evidence.claimVsObservation')}</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card min-w-0 p-4">
            <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-gray-300">{t('evidence.claimed')}</h3>
            {run.claims && Object.keys(run.claims).length > 0 ? (
              <dl className="space-y-3">
                {Object.entries(run.claims).map(([key, value]) => (
                  <div key={key}>
                    <dt className="mb-1 text-xs font-semibold text-gray-500">{key}</dt>
                    <dd className="whitespace-pre-wrap break-words text-sm text-gray-200">{claimValue(value)}</dd>
                  </div>
                ))}
              </dl>
            ) : <p className="text-sm text-gray-500">{t('evidence.noClaims')}</p>}
          </div>
          <div className="card min-w-0 p-4">
            <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-gray-300">{t('evidence.observed')}</h3>
            {verificationsQuery.isLoading ? (
              <div className="skeleton h-20 rounded" />
            ) : latestVerification?.checks?.length ? (
              <div className="space-y-4">
                {latestVerification.checks.map((check, index) => (
                  <article key={`${check.name}-${index}`} className="border-b border-surface-700 pb-3 last:border-0 last:pb-0">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-white">{check.name}</span>
                      <span data-testid={`check-outcome-${check.outcome}`} className={`text-xs font-semibold ${
                        check.outcome === 'pass' ? 'text-emerald-300' :
                          check.outcome === 'refuted' ? 'text-red-300' : 'text-violet-300'
                      }`}>{t(`evidence.checkOutcome.${check.outcome}`)}</span>
                    </div>
                    <p className="whitespace-pre-wrap break-words text-sm text-gray-300">{check.observation}</p>
                  </article>
                ))}
              </div>
            ) : <p className="text-sm text-gray-500">{t('evidence.noObservations')}</p>}
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-sm font-semibold text-gray-400">{t('evidence.verdictLabel')}:</span>
          <Verdict status={verdict} />
          {latestVerification && <span className="text-xs text-gray-500">{new Date(latestVerification.observed_at).toLocaleString()}</span>}
        </div>
      </section>

      <section className="card p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-white">{t('evidence.verificationHistory')}</h2>
          <button
            onClick={() => verifyMutation.mutate()}
            disabled={verifyMutation.isPending}
            className="btn btn-primary btn-sm inline-flex items-center gap-2"
          >
            {verifyMutation.isPending && <Loader2 size={14} className="animate-spin" />}
            {t('evidence.verify')}
          </button>
        </div>
        {verifyMutation.isError && <p role="alert" className="mb-3 text-sm text-red-300">{t('evidence.verifyError')}</p>}
        {verificationsQuery.isError ? <p role="alert" className="text-sm text-red-300">{t('evidence.historyError')}</p> :
          verifications.length === 0 ? <p className="text-sm text-gray-500">{t('evidence.noVerifications')}</p> : (
            <ol className="space-y-3">
              {verifications.map((verification, index) => (
                <li key={verification.id} className="rounded-lg border border-surface-700 p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-gray-500">#{index + 1}</span>
                    <Verdict status={verification.verdict} />
                    <time className="text-xs text-gray-500">{new Date(verification.observed_at).toLocaleString()}</time>
                  </div>
                  {verification.checks?.map((check, checkIndex) => (
                    <p key={`${check.name}-${checkIndex}`} className="text-sm text-gray-300">
                      <span className="font-semibold">{check.name}:</span> {check.observation}
                    </p>
                  ))}
                </li>
              ))}
            </ol>
          )}
      </section>

      <section className="card p-4">
        <h2 className="mb-3 text-lg font-semibold text-white">{t('evidence.approvalHistory')}</h2>
        {approvalsQuery.isLoading ? <div className="skeleton h-16 rounded" /> :
          approvalsQuery.isError ? <p role="alert" className="text-sm text-red-300">{t('evidence.historyError')}</p> :
            (approvalsQuery.data?.approvals.length ?? 0) === 0 ? <p className="text-sm text-gray-500">{t('evidence.noApprovals')}</p> : (
              <ol className="space-y-3">
                {approvalsQuery.data!.approvals.map(approval => (
                  <li key={approval.id} className="rounded-lg border border-surface-700 p-3">
                    <p className="text-sm font-semibold text-gray-200">
                      {t(`evidence.approval.${approval.decision}`)} · {approval.approver_name}
                    </p>
                    <time className="text-xs text-gray-500">{new Date(approval.decided_at).toLocaleString()}</time>
                    {approval.feedback && <p className="mt-2 whitespace-pre-wrap text-sm text-gray-300">{approval.feedback}</p>}
                    {approval.rejection_category && <p className="mt-1 text-xs text-gray-500">{t('evidence.category')}: {t(`evidence.categoryValues.${approval.rejection_category}`)}</p>}
                  </li>
                ))}
              </ol>
            )}
      </section>

      <section className="card p-4">
        <h2 className="mb-3 text-lg font-semibold text-white">{t('evidence.humanReview')}</h2>
        {run.reviewed_by && (
          <aside className="mb-4 rounded-lg border border-surface-700 p-3 text-sm" aria-label={t('evidence.suggestionTitle')}>
            <p className="text-xs font-semibold text-gray-400">{t('evidence.suggestionTitle')} · {run.reviewed_by}</p>
            {run.suggested_decision ? (
              <>
                <p className="mt-1 font-semibold text-gray-200">
                  {t(`evidence.approval.${run.suggested_decision}`)}
                  {run.suggested_category ? ` · ${t(`evidence.categoryValues.${run.suggested_category}`)}` : ''}
                </p>
                {run.suggested_reason && <p className="mt-1 whitespace-pre-wrap text-gray-300">{run.suggested_reason}</p>}
              </>
            ) : (
              <p className="mt-1 text-gray-400">{t('evidence.suggestionUnusable')}</p>
            )}
            <p className="mt-2 text-xs text-gray-500">{t('evidence.suggestionNote')}</p>
          </aside>
        )}
        <form onSubmit={submitApproval} className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-gray-400">
            {t('evidence.approverName')}
            <input className="input mt-1 w-full" value={approverName} onChange={event => setApproverName(event.target.value)} />
          </label>
          <label className="text-sm text-gray-400">
            {t('evidence.decision')}
            <select
              className="input mt-1 w-full"
              value={decision}
              onChange={event => {
                const nextDecision = event.target.value as 'approved' | 'rejected'
                setDecision(nextDecision)
                if (nextDecision === 'approved') setCategory('')
                setFormError('')
              }}
            >
              <option value="approved">{t('evidence.approval.approved')}</option>
              <option value="rejected">{t('evidence.approval.rejected')}</option>
            </select>
          </label>
          <label className="text-sm text-gray-400 md:col-span-2">
            {t('evidence.feedback')}{decision === 'rejected' ? ' *' : ''}
            <textarea className="textarea mt-1 w-full" rows={3} value={feedback} onChange={event => { setFeedback(event.target.value); setFormError('') }} />
          </label>
          {decision === 'rejected' && (
            <label className="text-sm text-gray-400 md:col-span-2">
              {t('evidence.rejectionCategory')}
              <select className="input mt-1 w-full" value={category} onChange={event => setCategory(event.target.value)}>
                <option value="">{t('evidence.noCategory')}</option>
                {REJECTION_CATEGORIES.map(value => (
                  <option key={value} value={value}>{t(`evidence.categoryValues.${value}`)}</option>
                ))}
              </select>
            </label>
          )}
          {formError && <p role="alert" className="text-sm text-red-300 md:col-span-2">{formError}</p>}
          {approveMutation.isError && <p role="alert" className="text-sm text-red-300 md:col-span-2">{t('evidence.approvalError')}</p>}
          {approveMutation.isSuccess && <p role="status" className="text-sm text-emerald-300 md:col-span-2">{t('evidence.approvalSaved')}</p>}
          <button type="submit" disabled={approveMutation.isPending} className="btn btn-primary md:col-span-2 md:justify-self-start">
            {approveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
            {t('evidence.submitReview')}
          </button>
        </form>
      </section>

      <section className="card p-4">
        <h2 className="mb-3 text-lg font-semibold text-white">{t('evidence.signatureStatus')}</h2>
        {auditQuery.isLoading ? <div className="skeleton h-16 rounded" /> :
          auditQuery.error instanceof ApiError && auditQuery.error.status === 404 ? (
            <p className="text-sm text-gray-400">{t('evidence.noAuditRows')}</p>
          ) : auditQuery.isError ? (
            <p role="alert" className="text-sm text-red-300">{t('evidence.auditError')}</p>
          ) : audit ? (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {SIGNATURE_STATUSES.map(status => {
                  const Icon = status === 'valid' ? ShieldCheck : status === 'invalid' ? ShieldAlert : ShieldQuestion
                  return (
                    <span key={status} data-testid={`signature-${status}`} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${SIGNATURE_STYLES[status]}`}>
                      <Icon size={13} aria-hidden="true" />
                      {t(`evidence.signature.${status}`)}: {audit.summary[status]}
                    </span>
                  )
                })}
              </div>
              <h3 className="mb-2 text-sm font-semibold text-gray-300">{t('evidence.auditLineage')}</h3>
              {audit.rows.length === 0 ? <p className="text-sm text-gray-500">{t('evidence.noAuditRows')}</p> :
                <ul className="space-y-2">
                  {audit.rows.map(row => (
                    <li key={row.id} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-mono text-gray-400">#{row.id}</span>
                      <span className="text-gray-300">{row.action}</span>
                      {row.legacy && (
                        <span data-testid="legacy-company" className={`rounded border px-2 py-0.5 text-xs ${SIGNATURE_STYLES.legacy}`}>
                          {t('evidence.legacyCompany')}
                        </span>
                      )}
                      <span data-testid={`signature-row-${row.status}`} className={`rounded border px-2 py-0.5 text-xs ${SIGNATURE_STYLES[row.status]}`}>
                        {t(`evidence.signature.${row.status}`)}
                      </span>
                    </li>
                  ))}
                </ul>}
            </>
          ) : null}
        <p className="mt-3 text-xs text-gray-500">
          {t('evidence.runAuditId')}: {run.audit_log_id ?? t('evidence.notRecorded')}
          {latestVerification?.audit_log_id !== undefined && latestVerification.audit_log_id !== null
            ? ` · ${t('evidence.latestVerificationAuditId')}: ${latestVerification.audit_log_id}` : ''}
        </p>
      </section>
    </div>
  )
}


const REJECTION_CATEGORIES = ['scope', 'quality', 'security', 'other'] as const
const SIGNATURE_STATUSES = ['valid', 'invalid', 'unsigned', 'legacy'] as const

export default function EvidenceDetail() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const { runId: rawRunId } = useParams()
  const runId = parseRouteId(rawRunId)

  if (companyId === null) {
    return <div className="page-container"><div className="empty-state py-16"><p className="text-gray-400">{t('evidence.selectCompany')}</p></div></div>
  }
  if (runId === null) {
    return <div className="page-container">
      <p role="alert" className="alert-error mb-4">{t('evidence.invalidId', { id: rawRunId })}</p>
      <Link to="/evidence" className="btn btn-ghost">{t('evidence.backToRuns')}</Link>
    </div>
  }

  return <div className="page-container max-w-6xl"><RunDetail companyId={companyId} runId={runId} /></div>
}
