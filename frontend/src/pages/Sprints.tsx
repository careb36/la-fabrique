/**
 * Sprints — every sprint of the selected company, active ones first, plus the
 * planner to launch the next one.
 */
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CalendarDays, Layers } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { useSprints } from '../hooks/useQueries'
import type { SprintSummary } from '../services/api'
import { QuickLaunch } from './Dashboard'
import { sprintPath } from './SprintWorkspace'
import { LearningTrend } from '../components/LearningTrend'

const STATUS_TONE: Record<string, string> = {
  active: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  needs_split: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  paused: 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20',
  completed: 'bg-surface-800 text-gray-400 border-surface-700',
  cancelled: 'bg-red-500/10 text-red-300 border-red-500/20',
}

function activeFirst(sprints: SprintSummary[]) {
  // Array.prototype.sort is stable, so the API's newest-first order survives within each group.
  return [...sprints].sort((a, b) => Number(b.status === 'active') - Number(a.status === 'active'))
}

function SprintRow({ sprint, current }: { sprint: SprintSummary; current: boolean }) {
  const { t } = useTranslation()
  const pct = sprint.total > 0 ? Math.round((sprint.done / sprint.total) * 100) : 0
  return (
    <li className="card grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto_12rem_8rem] sm:items-center">
      <div className="min-w-0">
        <Link to={sprintPath(sprint.id)} className="block truncate text-sm font-semibold text-white hover:text-brand-300">
          {sprint.sprint_name}
        </Link>
        {sprint.goal && <p className="mt-0.5 truncate text-xs text-gray-500">{sprint.goal}</p>}
        {current && (
          <p className="mt-0.5 text-[11px] text-brand-300">{t('sprints.lastOpened', { defaultValue: 'Last opened' })}</p>
        )}
      </div>
      <span className={`w-fit rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_TONE[sprint.status] ?? STATUS_TONE.completed}`}>
        {t(`dashboard.status.${sprint.status}`, { defaultValue: sprint.status })}
      </span>
      <div>
        <div className="mb-1 flex justify-between text-[11px] text-gray-500">
          <span>{t('sprints.progress', { defaultValue: '{{done}} / {{total}} done', done: sprint.done, total: sprint.total })}</span>
          <span className="tabular-nums">{pct}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-surface-700" aria-hidden="true">
          <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
        </div>
        {(sprint.blocked > 0 || sprint.rework > 0) && (
          <p className="mt-1 text-[11px] text-gray-500">
            {[
              sprint.blocked > 0 && t('sprints.blockedCount', { count: sprint.blocked, defaultValue: '{{count}} blocked' }),
              sprint.rework > 0 && t('sprints.reworkCount', { count: sprint.rework, defaultValue: '{{count}} rework requests' }),
            ].filter(Boolean).join(' · ')}
          </p>
        )}
      </div>
      <p className="flex items-center gap-1 text-xs text-gray-400">
        <CalendarDays size={12} className="shrink-0" />
        {sprint.start_date ?? t('sprints.noStartDate', { defaultValue: 'Not started' })}
      </p>
    </li>
  )
}

export default function Sprints() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const activeSprintId = useAppStore(state => state.activeSprintId)
  const setActiveSprint = useAppStore(state => state.setActiveSprint)
  const { data, isLoading, isError, refetch } = useSprints(companyId)
  const sprints = activeFirst(data ?? [])

  return (
    <div className="page-container max-w-6xl space-y-6">
      <header className="page-header mb-0">
        <div>
          <h1 className="page-title">{t('nav.sprints', { defaultValue: 'Sprints' })}</h1>
          <p className="page-subtitle">{t('sprints.subtitle', { defaultValue: 'Every sprint of this company, active ones first.' })}</p>
        </div>
      </header>

      {companyId === null ? (
        <div className="empty-state">
          <p className="empty-state-title">{t('sprints.selectCompany', { defaultValue: 'Select a company to see its sprints.' })}</p>
          <Link to="/companies/select" className="btn btn-ghost">{t('workspace.selectCompany', { defaultValue: 'Select company' })}</Link>
        </div>
      ) : isLoading ? (
        <div role="status" aria-label={t('common.loading', { defaultValue: 'Loading...' })} className="space-y-3">
          {[0, 1, 2].map(index => <div key={index} className="skeleton h-16 rounded-card" />)}
        </div>
      ) : isError ? (
        <div role="alert" className="alert-error">
          {t('sprints.loadError', { defaultValue: 'Failed to load sprints.' })}
          <button type="button" className="btn btn-ghost btn-sm ml-auto" onClick={() => refetch()}>{t('common.retry', { defaultValue: 'Retry' })}</button>
        </div>
      ) : sprints.length === 0 ? (
        <div className="empty-state rounded-card border border-dashed border-surface-700">
          <Layers size={28} className="empty-state-icon" />
          <p className="empty-state-title">{t('sprints.emptyTitle', { defaultValue: 'No sprints yet' })}</p>
          <p className="empty-state-desc">{t('sprints.emptyDescription', { defaultValue: 'Plan a sprint below, or create a new company with a foundation sprint.' })}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <a href="#plan-sprint" className="btn btn-primary btn-sm">{t('sprints.planSprint', { defaultValue: 'Plan a sprint' })}</a>
            <Link to="/companies/new" className="btn btn-ghost btn-sm">{t('nav.newCompany', { defaultValue: 'New company' })}</Link>
          </div>
        </div>
      ) : (
        <>
          <LearningTrend sprints={sprints} />
          <ul className="space-y-2" aria-label={t('nav.sprints', { defaultValue: 'Sprints' })}>
            {sprints.map(sprint => <SprintRow key={sprint.id} sprint={sprint} current={sprint.id === activeSprintId} />)}
          </ul>
        </>
      )}

      <section id="plan-sprint" aria-label={t('sprints.planSprint', { defaultValue: 'Plan a sprint' })} className="scroll-mt-20">
        <QuickLaunch onSuccess={id => setActiveSprint(id)} />
      </section>
    </div>
  )
}
