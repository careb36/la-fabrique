/**
 * Controls over when a sprint's agents work.
 *
 * - `SprintStatusBanner` (every tab): a planned sprint offers Start, a paused
 *   one says why (a person, or a provider without credit) and offers Resume.
 * - `SprintControls` (Board tab): dispatch pending tasks, pause, stop for good,
 *   and the company's autonomy level.
 * - `StartChoice` (New company wizard): start Sprint 0 now or leave it planned.
 */
import React from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Pause, Play, Send, Square } from 'lucide-react'
import { useCurrentRole, useDispatchSprint, usePauseSprint, useResumeSprint } from '../hooks/useQueries'
import { useToast } from '../store/toastStore'
import { errorDetail } from '../services/api'
import { type SprintState, useAutonomy, useSetAutonomy, useStartSprint, useStopSprint } from '../services/workControl'

const AUTONOMY_LEVELS = [1, 2, 3] as const

function useFailure() {
  const [failed, setFailed] = React.useState<{ retry: () => void; message: string } | null>(null)
  const track = (retry: () => void) => ({
    onError: (error: unknown) => setFailed({ retry, message: errorDetail(error) }),
  })
  return { failed, clear: () => setFailed(null), track }
}

function Failure({ failed }: { failed: { retry: () => void; message: string } | null }) {
  const { t } = useTranslation()
  if (!failed) return null
  return (
    <div role="alert" className="flex items-center gap-2 text-xs text-red-300">
      <span>{t('workspace.sprintActionFailed', { message: failed.message, defaultValue: 'Could not complete the action: {{message}}' })}</span>
      <button type="button" onClick={failed.retry} className="underline">{t('common.retry')}</button>
    </div>
  )
}

/** Shown on every tab while the sprint does not run: Start or Resume it. */
export function SprintStatusBanner({ sprint }: { sprint: SprintState }) {
  const { t } = useTranslation()
  const start = useStartSprint()
  const resume = useResumeSprint()
  const { failed, clear, track } = useFailure()
  if (sprint.status !== 'planned' && sprint.status !== 'paused') return null
  const planned = sprint.status === 'planned'
  const run = () => {
    clear()
    if (planned) start.mutate(sprint.id, track(run))
    else resume.mutate(sprint.id, track(run))
  }
  const busy = start.isPending || resume.isPending
  return (
    <div className={`rounded-xl border p-3 ${planned ? 'border-brand-500/40 bg-brand-500/10' : 'border-yellow-500/40 bg-yellow-500/10'}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 text-sm">
          <p className="font-medium text-white">
            {planned
              ? t('workControl.plannedTitle', { defaultValue: 'This sprint has not started' })
              : t('workControl.pausedTitle', { defaultValue: 'This sprint is paused' })}
          </p>
          <p className="text-gray-300">
            {planned
              ? t('workControl.plannedHint', { defaultValue: 'The agents start working when you start it.' })
              : sprint.pause_reason || t('workControl.pausedHint', { defaultValue: 'Nothing is dispatched, reviewed or retried until it is resumed.' })}
          </p>
        </div>
        <button type="button" disabled={busy} onClick={run}
          className="btn-primary btn-sm flex items-center gap-1.5">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {planned ? t('workControl.start', { defaultValue: 'Start' }) : t('workspace.resumeSprint', { defaultValue: 'Resume' })}
        </button>
      </div>
      <Failure failed={failed} />
    </div>
  )
}

function AutonomyControl({ companyId, canManage }: { companyId: number; canManage: boolean }) {
  const { t } = useTranslation()
  const autonomy = useAutonomy(companyId)
  const setAutonomy = useSetAutonomy(companyId)
  const level = autonomy.data?.autonomy_level
  if (level === undefined) return null
  return (
    <label className="flex items-center gap-1.5 text-xs text-gray-400"
      title={t(`workControl.autonomyHint.${level}`, { defaultValue: '' })}>
      {t('workControl.autonomy', { defaultValue: 'Autonomy' })}
      <select value={level} disabled={!canManage || setAutonomy.isPending}
        onChange={event => setAutonomy.mutate(Number(event.target.value))}
        className="rounded border border-surface-700 bg-surface-900 px-1.5 py-0.5 text-xs text-gray-200">
        {AUTONOMY_LEVELS.map(value => (
          <option key={value} value={value}>{t(`workControl.autonomyLevel.${value}`, { defaultValue: String(value) })}</option>
        ))}
      </select>
    </label>
  )
}

/** Board-tab controls: dispatch pending tasks, pause, stop, autonomy. */
export function SprintControls({ sprint }: { sprint: SprintState }) {
  const { t } = useTranslation()
  const toast = useToast()
  const role = useCurrentRole()
  const canManage = role === 'Owner' || role === 'Manager'
  const dispatchMutation = useDispatchSprint()
  const pauseMutation = usePauseSprint()
  const stopMutation = useStopSprint()
  const { failed, clear, track } = useFailure()
  const busy = dispatchMutation.isPending || pauseMutation.isPending || stopMutation.isPending
  const running = sprint.status === 'active' || sprint.status === 'needs_split'
  const finished = sprint.status === 'completed' || sprint.status === 'cancelled'

  const dispatch = () => {
    clear()
    dispatchMutation.mutate(sprint.id, {
      ...track(dispatch),
      onSuccess: result => toast.success(result.dispatched > 0
        ? t('workspace.dispatched', { count: result.dispatched, defaultValue: '{{count}} task(s) sent to the agents' })
        : t('workspace.nothingToDispatch', { defaultValue: 'No pending tasks to dispatch' })),
    })
  }
  const pause = () => { clear(); pauseMutation.mutate(sprint.id, track(pause)) }
  const stop = () => {
    if (!window.confirm(t('workControl.stopConfirm', { defaultValue: 'Stop this sprint for good? Unfinished tasks are blocked and no follow-up sprint opens.' }))) return
    clear()
    stopMutation.mutate(sprint.id, track(stop))
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap items-center justify-end gap-1">
        <AutonomyControl companyId={sprint.company_id} canManage={canManage} />
        <button type="button" disabled={busy || !running} onClick={dispatch}
          title={running ? undefined : t('workspace.dispatchPausedHint', { defaultValue: 'Resume the sprint to dispatch tasks' })}
          className="btn-ghost btn-sm flex items-center gap-1.5 text-brand-300">
          {dispatchMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
          {t('workspace.dispatchSprint', { defaultValue: 'Dispatch pending' })}
        </button>
        {running && (
          <button type="button" disabled={busy} onClick={pause}
            className="btn-ghost btn-sm flex items-center gap-1.5 text-yellow-400">
            {pauseMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Pause size={13} />}
            {t('workspace.pauseSprint', { defaultValue: 'Pause' })}
          </button>
        )}
        {!finished && (
          <button type="button" disabled={busy} onClick={stop}
            className="btn-ghost btn-sm flex items-center gap-1.5 text-red-400">
            {stopMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
            {t('workControl.stop', { defaultValue: 'Stop' })}
          </button>
        )}
      </div>
      <Failure failed={failed} />
    </div>
  )
}

/** The wizard's choice: start Sprint 0 when the company is created, or not. */
export function StartChoice({ checked, humanLed, onChange }: { checked: boolean; humanLed: boolean; onChange: (value: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <label className="mt-3 flex items-start gap-2 text-sm text-gray-300">
      <input type="checkbox" checked={checked && !humanLed} disabled={humanLed}
        onChange={event => onChange(event.target.checked)} className="mt-0.5" />
      <span>
        {t('workControl.startNow', { defaultValue: 'Start Sprint 0 as soon as the company is created' })}
        <span className="block text-xs text-gray-500">
          {humanLed
            ? t('workControl.startNowHumanLed', { defaultValue: 'At level 1 you always start it yourself.' })
            : t('workControl.startNowHint', { defaultValue: 'Leave it unchecked to review the plan first and start it from the sprint page.' })}
        </span>
      </span>
    </label>
  )
}
