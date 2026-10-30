/**
 * Sprint page — one page per sprint at `/sprints/:id`, with five tabs:
 * Overview (`/sprints/:id`), Board (`/board`), Live (`/live`), Conversation
 * (`/conversation`) and Analytics (`/analytics`). An unknown tab falls back to
 * Overview.
 *
 * The page validates the sprint before rendering any tab, and only remembers
 * it as the active sprint when it belongs to the selected company; a sprint of
 * another company stays read-only.
 */
import React, { useEffect } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, MonitorPlay, Pause, Play, Radio, Send } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { useAgentStore } from '../store/agentStore'
import GlassRoom from '../components/GlassRoom'
import KanbanBoard from '../components/KanbanBoard'
import { AnalyticsDashboard } from '../components/AnalyticsDashboard'
import { Conversation } from '../components/Conversation'
import { Breadcrumbs } from '../components/Breadcrumbs'
import SprintOverview from './Dashboard'
import { useDispatchSprint, usePauseSprint, useResumeSprint, useSprintBoard } from '../hooks/useQueries'
import { useToast } from '../store/toastStore'
import { ApiError, errorDetail } from '../services/api'
import { parseRouteId } from '../lib/routeId'

export const SPRINT_TABS = ['overview', 'board', 'live', 'conversation', 'analytics'] as const
export type SprintTab = typeof SPRINT_TABS[number]

const TAB_LABELS: Record<SprintTab, { key: string; defaultValue: string }> = {
  overview: { key: 'sprint.tabs.overview', defaultValue: 'Overview' },
  board: { key: 'sprint.tabs.board', defaultValue: 'Board' },
  live: { key: 'sprint.tabs.live', defaultValue: 'Live' },
  conversation: { key: 'sprint.tabs.conversation', defaultValue: 'Conversation' },
  analytics: { key: 'sprint.tabs.analytics', defaultValue: 'Analytics' },
}

export function sprintPath(id: number | string, tab: SprintTab = 'overview') {
  return tab === 'overview' ? `/sprints/${id}` : `/sprints/${id}/${tab}`
}

function isSprintTab(value: string): value is SprintTab {
  return (SPRINT_TABS as readonly string[]).includes(value)
}

function SprintTabs({ sprintId, selected }: { sprintId: number; selected: SprintTab }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <div role="tablist" aria-label={t('sprint.views', { defaultValue: 'Sprint views' })}
      className="flex min-w-0 gap-1 overflow-x-auto"
      onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const current = SPRINT_TABS.indexOf(selected)
        const next = event.key === 'Home' ? 0
          : event.key === 'End' ? SPRINT_TABS.length - 1
          : (current + (event.key === 'ArrowLeft' ? -1 : 1) + SPRINT_TABS.length) % SPRINT_TABS.length
        navigate(sprintPath(sprintId, SPRINT_TABS[next]))
        event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus()
      }}>
      {SPRINT_TABS.map(tab => {
        const isSelected = tab === selected
        return (
          <Link key={tab} id={`sprint-tab-${tab}`} role="tab" to={sprintPath(sprintId, tab)}
            aria-selected={isSelected} aria-controls="sprint-panel" tabIndex={isSelected ? 0 : -1}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              isSelected
                ? 'border-brand-500 text-white'
                : 'border-transparent text-gray-400 hover:text-white'
            }`}>
            {t(TAB_LABELS[tab].key, { defaultValue: TAB_LABELS[tab].defaultValue })}
          </Link>
        )
      })}
    </div>
  )
}

function LivePanel({ sprintId }: { sprintId: number }) {
  const { t } = useTranslation()
  const isSSEConnected = useAgentStore(s => s.isConnected)
  const messageCount = useAgentStore(s => s.messages.length)
  return (
    <div className="card flex min-h-[32rem] flex-col overflow-visible xl:h-[calc(100vh-14rem)] xl:overflow-hidden">
      <div className="flex min-h-11 flex-wrap items-center gap-3 border-b border-surface-700 bg-surface-900 px-4 py-2">
        <MonitorPlay size={15} className="text-brand-400" />
        <span className={`h-1.5 w-1.5 rounded-full ${isSSEConnected ? 'animate-pulse bg-green-400' : 'bg-red-500'}`} />
        <span className="text-xs text-gray-400">
          {isSSEConnected
            ? t('sprint.streamConnected', { defaultValue: 'Stream connected' })
            : t('sprint.streamDisconnected', { defaultValue: 'Stream disconnected' })}
        </span>
        {messageCount > 0 && (
          <span className="rounded-full bg-brand-700/40 px-1.5 py-0.5 text-[10px] font-medium text-brand-300">
            {messageCount}
          </span>
        )}
        <span className="ml-auto hidden items-center gap-1 text-xs text-gray-500 sm:flex">
          <Radio size={11} /> {t('workspace.aiAgentsActive', { defaultValue: 'AI Agents Active' })}
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <GlassRoom sprintId={String(sprintId)} />
      </div>
    </div>
  )
}

function BoardPanel({ sprintId }: { sprintId: number }) {
  const { t } = useTranslation()
  return (
    <div className="card flex min-h-[34rem] flex-col overflow-hidden">
      <p className="border-b border-surface-700 bg-surface-900 px-4 py-2 text-xs text-gray-500">
        {t('workspace.boardOpsHint', { defaultValue: 'Drag tasks to change status or reassign' })}
      </p>
      <div className="min-h-0 flex-1">
        <KanbanBoard sprintId={String(sprintId)} />
      </div>
    </div>
  )
}

type SprintAction = 'dispatch' | 'pause' | 'resume'

/** Board-tab controls: dispatch pending tasks, pause and resume the sprint. */
function SprintControls({ sprintId, status }: { sprintId: number; status: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const dispatchMutation = useDispatchSprint()
  const pauseMutation = usePauseSprint()
  const resumeMutation = useResumeSprint()
  const [failed, setFailed] = React.useState<{ action: SprintAction; message: string } | null>(null)
  const busy = dispatchMutation.isPending || pauseMutation.isPending || resumeMutation.isPending
  const paused = status === 'paused'

  const run = (action: SprintAction) => {
    setFailed(null)
    const onError = (error: unknown) => setFailed({ action, message: errorDetail(error) })
    if (action === 'dispatch') {
      dispatchMutation.mutate(sprintId, {
        onSuccess: result => toast.success(result.dispatched > 0
          ? t('workspace.dispatched', { count: result.dispatched, defaultValue: '{{count}} task(s) sent to the agents' })
          : t('workspace.nothingToDispatch', { defaultValue: 'No pending tasks to dispatch' })),
        onError,
      })
    } else if (action === 'pause') {
      pauseMutation.mutate(sprintId, { onError })
    } else {
      resumeMutation.mutate(sprintId, { onError })
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1">
        <button type="button" disabled={busy || paused} onClick={() => run('dispatch')}
          title={paused ? t('workspace.dispatchPausedHint', { defaultValue: 'Resume the sprint to dispatch tasks' }) : undefined}
          className="btn-ghost btn-sm flex items-center gap-1.5 text-brand-300">
          {dispatchMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
          {t('workspace.dispatchSprint', { defaultValue: 'Dispatch pending' })}
        </button>
        {paused ? (
          <button type="button" disabled={busy} onClick={() => run('resume')}
            className="btn-ghost btn-sm flex items-center gap-1.5 text-emerald-400">
            {resumeMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {t('workspace.resumeSprint', { defaultValue: 'Resume' })}
          </button>
        ) : (
          <button type="button" disabled={busy} onClick={() => run('pause')}
            className="btn-ghost btn-sm flex items-center gap-1.5 text-yellow-400">
            {pauseMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}
            {t('workspace.pauseSprint', { defaultValue: 'Pause' })}
          </button>
        )}
      </div>
      {failed && (
        <div role="alert" className="flex items-center gap-2 text-xs text-red-300">
          <span>{t('workspace.sprintActionFailed', { message: failed.message, defaultValue: 'Could not complete the action: {{message}}' })}</span>
          <button type="button" onClick={() => run(failed.action)} className="underline">
            {t('common.retry')}
          </button>
        </div>
      )}
    </div>
  )
}

export const SprintWorkspace: React.FC = () => {
  const { id, tab: rawTab } = useParams<{ id: string; tab?: string }>()
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const setActiveSprint = useAppStore(state => state.setActiveSprint)
  const sprintId = parseRouteId(id)
  const requestedTab = rawTab?.toLowerCase()
  const tab: SprintTab = requestedTab && isSprintTab(requestedTab) ? requestedTab : 'overview'
  const boardQuery = useSprintBoard(sprintId)
  const notFound = boardQuery.error instanceof ApiError && boardQuery.error.status === 404
  const noAccess = boardQuery.error instanceof ApiError && boardQuery.error.status === 403
  const terminalMessage = noAccess
    ? t('workspace.noAccess', { id, defaultValue: 'You no longer have access to sprint #{{id}}.' })
    : notFound
      ? t('workspace.notFound', { id, defaultValue: 'Sprint #{{id}} was not found.' })
      : null

  useEffect(() => {
    if (sprintId !== null && boardQuery.data && !boardQuery.isError && boardQuery.data.sprint.company_id === companyId) {
      setActiveSprint(sprintId)
    }
  }, [sprintId, boardQuery.data, boardQuery.isError, companyId, setActiveSprint])

  const sprintsLabel = t('nav.sprints', { defaultValue: 'Sprints' })

  if (sprintId === null || (boardQuery.isError && !boardQuery.data)) {
    const message = sprintId === null
      ? t('workspace.invalidId', { id, defaultValue: 'Invalid sprint ID: {{id}}.' })
      : terminalMessage ?? t('workspace.loadError', { id, defaultValue: 'Failed to load sprint #{{id}}.' })
    return (
      <div className="page-container">
        <div role="alert" className="alert-error mb-4">
          {message}
        </div>
        {sprintId !== null && !notFound && !noAccess && (
          <button className="btn btn-ghost mr-3" onClick={() => boardQuery.refetch()}>{t('common.retry', { defaultValue: 'Retry' })}</button>
        )}
        <Link to="/sprints" className="btn btn-ghost">{sprintsLabel}</Link>
      </div>
    )
  }

  // Normalise `/sprints/:id/overview` and unknown tabs to the canonical Overview URL.
  if (rawTab !== undefined && tab === 'overview') {
    return <Navigate to={sprintPath(sprintId)} replace />
  }

  const board = boardQuery.data
  const sprintName = board?.sprint.sprint_name || t('workspace.sprintLabel', { id: sprintId, defaultValue: 'Sprint #{{id}}' })
  const wide = tab === 'board' || tab === 'live'

  return (
    <div className="bg-surface-950 px-4 pb-24 pt-4 text-white lg:px-6">
      <div className={`mx-auto min-w-0 space-y-4 ${wide ? 'max-w-[1920px]' : 'max-w-6xl'}`}>
        <Breadcrumbs items={[{ label: sprintsLabel, to: '/sprints' }, { label: sprintName }]} />
        {board && board.sprint.company_id !== companyId && (
          <div role="alert" className="alert-error p-3">
            {t('workspace.otherCompany', { defaultValue: 'This sprint belongs to another company. This view is read-only.' })}
            {' '}
            <Link to="/companies/select" className="underline">{t('workspace.selectCompany', { defaultValue: 'Select company' })}</Link>
          </div>
        )}
        {boardQuery.isError && (
          <div role="alert" className="alert-error p-3">
            {terminalMessage ?? t('workspace.refreshFailed', { defaultValue: 'Failed to refresh this sprint. Showing the last loaded view.' })}
            {!noAccess && !notFound && (
              <button className="btn btn-ghost ml-3" onClick={() => boardQuery.refetch()}>{t('common.retry', { defaultValue: 'Retry' })}</button>
            )}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="min-w-0 truncate text-xl font-bold tracking-tight text-white">{sprintName}</h1>
          {board?.sprint.status && (
            <span className="rounded-full border border-surface-700 bg-surface-900 px-2 py-0.5 text-[11px] text-gray-400">
              {t(`dashboard.status.${board.sprint.status}`, { defaultValue: board.sprint.status })}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-2 border-b border-surface-700">
          <SprintTabs sprintId={sprintId} selected={tab} />
          {tab === 'board' && board && (
            <div className="ml-auto pb-1">
              <SprintControls sprintId={sprintId} status={board.sprint.status} />
            </div>
          )}
        </div>
        <div id="sprint-panel" role="tabpanel" aria-labelledby={`sprint-tab-${tab}`} className="min-w-0">
          {!board ? (
            <div role="status" className="py-8 text-sm text-gray-400">{t('common.loading', { defaultValue: 'Loading...' })}</div>
          ) : tab === 'board' ? (
            <BoardPanel sprintId={sprintId} />
          ) : tab === 'live' ? (
            <LivePanel sprintId={sprintId} />
          ) : tab === 'conversation' ? (
            <Conversation companyId={board.sprint.company_id} sprintId={sprintId} live={board.sprint.status === 'active'} />
          ) : tab === 'analytics' ? (
            <AnalyticsDashboard sprintId={sprintId} />
          ) : (
            <SprintOverview sprintId={sprintId} />
          )}
        </div>
      </div>
    </div>
  )
}
