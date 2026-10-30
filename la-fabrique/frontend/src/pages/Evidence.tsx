import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FileSearch, RefreshCw } from 'lucide-react'
import { useAgentRuns } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import { Verdict, VERDICT_PRESENTATION } from '../components/Verdict'
import type { AgentRunListItem, AgentRunStatus } from '../services/api'

const STATUSES = Object.keys(VERDICT_PRESENTATION) as AgentRunStatus[]

/** A clickable count that filters the list by one verdict. The "refuted" chip
 *  keeps its red ring even when inactive, so the number that needs a person
 *  never gets lost among the rest (isolation effect). */
function SummaryChip({ label, count, active, variant, onClick }: {
  label: string
  count: number
  active: boolean
  variant: AgentRunStatus | 'all'
  onClick: () => void
}) {
  const attention = variant === 'refuted'
  const classes = active
    ? 'border-brand-500 bg-brand-950/40 text-white ring-1 ring-brand-500'
    : attention
      ? 'border-red-800/60 bg-red-950/40 text-red-200 hover:border-red-700/60'
      : 'border-surface-700 bg-surface-800 text-gray-300 hover:border-surface-600'
  return (
    <button
      type="button"
      data-testid={`summary-${variant}`}
      aria-pressed={active}
      onClick={onClick}
      className={`flex flex-col items-center gap-0.5 rounded-lg border px-2 py-3 transition-colors ${classes}`}
    >
      <span className="text-xl font-bold leading-none">{count}</span>
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}

function EvidenceRuns({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useAgentRuns(companyId, { limit: 500 })
  const [producer, setProducer] = useState('')
  const [status, setStatus] = useState<AgentRunStatus | ''>('')
  const [from, setFrom] = useState('')
  const [until, setUntil] = useState('')

  const runs = data?.agent_runs ?? []
  const producers = useMemo(() => [...new Set(runs.map(run => run.producer))].sort(), [runs])
  const counts = useMemo(() => {
    const result: Record<AgentRunStatus, number> = { verified: 0, refuted: 0, unverifiable: 0, ingested: 0 }
    runs.forEach(run => { result[run.status] += 1 })
    return result
  }, [runs])
  const filteredRuns = runs.filter(run => {
    const date = run.ingested_at.slice(0, 10)
    return (!producer || run.producer === producer)
      && (!status || run.status === status)
      && (!from || date >= from)
      && (!until || date <= until)
  })
  const hasFilters = Boolean(producer || status || from || until)

  function clearFilters() {
    setProducer('')
    setStatus('')
    setFrom('')
    setUntil('')
  }

  if (isLoading) {
    return <div role="status" className="space-y-3" aria-label={t('evidence.loading')}>
      {[1, 2, 3].map(item => <div key={item} className="skeleton h-24 rounded-lg" />)}
    </div>
  }

  if (isError) {
    return (
      <div role="alert" className="alert-error flex items-center justify-between gap-3">
        <span>{t('evidence.error')}</span>
        <button onClick={() => refetch()} className="btn-ghost btn-sm flex items-center gap-1">
          <RefreshCw size={14} />{t('evidence.retry')}
        </button>
      </div>
    )
  }

  return (
    <>
      {runs.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label={t('evidence.summary.aria')}>
          <SummaryChip
            label={t('evidence.summary.all')}
            count={runs.length}
            active={status === ''}
            variant="all"
            onClick={() => setStatus('')}
          />
          {STATUSES.map(value => (
            <SummaryChip
              key={value}
              label={t(`evidence.verdict.${value}`)}
              count={counts[value]}
              active={status === value}
              variant={value}
              onClick={() => setStatus(status === value ? '' : value)}
            />
          ))}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-sm text-gray-400">
        {runs.length > 0
          ? <span>{t('evidence.showing', { shown: filteredRuns.length, total: runs.length })}</span>
          : <span aria-hidden="true" />}
        {hasFilters && (
          <button type="button" onClick={clearFilters} className="btn btn-ghost btn-sm">
            {t('evidence.clearFilters')}
          </button>
        )}
      </div>

      <details className="card mb-5 p-4">
        <summary className="cursor-pointer text-sm font-medium text-gray-300">{t('evidence.filters')}</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-sm text-gray-400">
            {t('evidence.producer')}
            <select className="input mt-1 w-full" value={producer} onChange={event => setProducer(event.target.value)}>
              <option value="">{t('evidence.allProducers')}</option>
              {producers.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="text-sm text-gray-400">
            {t('evidence.ingestedAfter')}
            <input className="input mt-1 w-full" type="date" value={from} onChange={event => setFrom(event.target.value)} />
          </label>
          <label className="text-sm text-gray-400">
            {t('evidence.ingestedBefore')}
            <input className="input mt-1 w-full" type="date" value={until} onChange={event => setUntil(event.target.value)} />
          </label>
        </div>
      </details>

      {filteredRuns.length === 0 ? (
        <div className="empty-state py-16">
          <FileSearch size={36} className="mx-auto mb-3 text-gray-600" />
          <p className="text-gray-400">{t('evidence.empty')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredRuns.map((run: AgentRunListItem) => (
            <Link
              key={run.id}
              to={`/evidence/${run.id}`}
              className="card card-hover flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Verdict status={run.status} />
                  <span className="badge bg-surface-700 text-gray-300">{run.producer}</span>
                  {run.agent_role && <span className="text-xs text-gray-500">{run.agent_role}</span>}
                </div>
                <p className="truncate font-mono text-sm text-gray-300">{run.external_ref}</p>
                <p className="mt-1 text-xs text-gray-500">{t('evidence.ingestedAt')}: {new Date(run.ingested_at).toLocaleString()}</p>
                {run.latest_approval && (
                  <p className="mt-2 text-sm text-gray-400">
                    {t('evidence.latestApproval')}: {t(`evidence.approval.${run.latest_approval.decision}`)}
                    {' · '}{run.latest_approval.approver_name}
                    {run.latest_approval.feedback ? ` — ${run.latest_approval.feedback}` : ''}
                  </p>
                )}
              </div>
              <span className="self-start text-sm font-medium text-brand-300 sm:self-auto">{t('evidence.viewDetails')} →</span>
            </Link>
          ))}
        </div>
      )}
    </>
  )
}

export default function Evidence() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)

  return (
    <div className="page-container max-w-6xl">
      <header className="page-header mb-6">
        <h1 className="page-title">{t('evidence.title')}</h1>
        <p className="mt-1 text-gray-400">{t('evidence.subtitle')}</p>
      </header>
      {companyId === null
        ? <div className="empty-state py-16"><p className="text-gray-400">{t('evidence.selectCompany')}</p></div>
        : <EvidenceRuns companyId={companyId} />}
    </div>
  )
}
