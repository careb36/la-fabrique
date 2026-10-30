/**
 * Sprint Overview — the default tab of a sprint page (`/sprints/:id`).
 *
 * Layout: KPI strip → alert banner → main grid (sprint card + agent roster) → quick launch.
 * Scope: read-only overview + sprint launch. Heavy state lives in stores/queries.
 * Navigation (tabs, breadcrumb, shell status) belongs to the sprint page and the
 * app shell, so nothing here repeats it.
 */

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import {
  Activity, AlertTriangle, Bot, CheckCircle2, ChevronRight,
  CircleDot, Cpu, Layers, Loader2, Play, Settings2,
  ShieldAlert, Sparkles, SplitSquareVertical, Target, Zap,
} from 'lucide-react'
import type { SprintPlanResponse } from '../services/api'
import { useAppStore } from '../store/useAppStore'
import { useAgentStore } from '../store/agentStore'
import { useSprintBoard, useAnalyticsSummary, useStartSprint, useInitCompany, usePlanSprint, usePlanSelfImprovementSprint, useQuotas, useInbox, useSprints } from '../hooks/useQueries'
import { secondAttempts } from '../lib/learningTrend'
import { SprintHealthChart } from '../components/SprintHealthChart'
import { LoadingSkeleton } from '../components/LoadingSkeleton'

// ── Constants ─────────────────────────────────────────────────────────────────

const SCOPE_META: Record<string, { label: string; limit: number; color: string; bg: string }> = {
  S: { label: 'Small',  limit: 4,  color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  M: { label: 'Medium', limit: 8,  color: 'text-brand-400',   bg: 'bg-brand-500/10 border-brand-500/20'    },
  L: { label: 'Large',  limit: 12, color: 'text-amber-400',   bg: 'bg-amber-500/10 border-amber-500/20'    },
}

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  active:      { label: 'Active',      color: 'text-emerald-400', dot: 'bg-emerald-400' },
  needs_split: { label: 'Needs Split', color: 'text-amber-400',   dot: 'bg-amber-400 animate-pulse' },
  completed:   { label: 'Completed',   color: 'text-gray-400',    dot: 'bg-gray-400'    },
  cancelled:   { label: 'Cancelled',   color: 'text-red-400',     dot: 'bg-red-400'     },
}

const PRIORITY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

// ── Atoms ─────────────────────────────────────────────────────────────────────

function KpiCard({
  icon: Icon, label, value, sub, accent = false, warn = false,
}: {
  icon: typeof Activity
  label: string
  value: string | number
  sub?: string
  accent?: boolean
  warn?: boolean
}) {
  return (
    <div className={`relative overflow-hidden rounded-xl border p-4 transition-shadow hover:shadow-card-md ${
      warn
        ? 'bg-amber-950/20 border-amber-500/25'
        : accent
          ? 'bg-brand-950/40 border-brand-600/25'
          : 'bg-surface-900 border-surface-700'
    }`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wider mb-1">{label}</p>
          <p className={`text-2xl font-bold tabular-nums ${
            warn ? 'text-amber-400' : accent ? 'text-brand-300' : 'text-white'
          }`}>
            {value}
          </p>
          {sub && <p className="text-[11px] text-gray-500 mt-0.5">{sub}</p>}
        </div>
        <div className={`p-2 rounded-lg ${
          warn ? 'bg-amber-500/10' : accent ? 'bg-brand-500/10' : 'bg-surface-800'
        }`}>
          <Icon size={16} className={warn ? 'text-amber-400' : accent ? 'text-brand-400' : 'text-gray-400'} />
        </div>
      </div>
    </div>
  )
}

function ScopeBadge({ scope }: { scope?: string }) {
  const { t } = useTranslation()
  const scopeKey = scope && SCOPE_META[scope] ? scope : 'M'
  const meta = SCOPE_META[scopeKey]
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-semibold ${meta.bg} ${meta.color}`}>
      <Layers size={10} />
      {t(`dashboard.scope.${scopeKey}.label`, { defaultValue: meta.label })}
    </span>
  )
}

function StatusBadge({ status }: { status?: string }) {
  const { t } = useTranslation()
  const statusKey = status && STATUS_META[status] ? status : 'active'
  const meta = STATUS_META[statusKey]
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium">
      <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
      <span className={meta.color}>{t(`dashboard.status.${statusKey}`, { defaultValue: meta.label })}</span>
    </span>
  )
}

function ProgressBar({ done, total }: { done: number; total: number }) {
  const { t } = useTranslation()
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div>
      <div className="flex justify-between text-[11px] text-gray-500 mb-1">
        <span>{t('dashboard.tasksDone', { defaultValue: '{{done}} of {{total}} tasks done', done, total })}</span>
        <span className="tabular-nums">{pct}%</span>
      </div>
      <div className="h-1.5 bg-surface-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-brand-500 to-brand-400 rounded-full transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ── Needs Split Alert ──────────────────────────────────────────────────────────

function NeedsSplitAlert({ sprintId, sprintName }: { sprintId: number; sprintName: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-start gap-3 p-4 rounded-xl border border-amber-500/30 bg-amber-950/20 animate-fade-in">
      <div className="p-2 rounded-lg bg-amber-500/10 shrink-0">
        <SplitSquareVertical size={16} className="text-amber-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-amber-300">{t('dashboard.needsSplit', { defaultValue: 'Sprint needs splitting' })}</p>
        <p className="text-xs text-amber-200/60 mt-0.5">
          <strong className="text-amber-200/80">{sprintName}</strong> {t('dashboard.needsSplitDesc', { defaultValue: 'This sprint exceeded agent capacity. Split it into smaller scopes.' })}
        </p>
      </div>
      <Link
        to={`/sprints/${sprintId}/live`}
        className="shrink-0 flex items-center gap-1 text-xs font-medium text-amber-400 hover:text-amber-300 transition-colors"
      >
        {t('dashboard.review', { defaultValue: 'Review' })} <ChevronRight size={12} />
      </Link>
    </div>
  )
}

// ── Agent Roster ──────────────────────────────────────────────────────────────

const ROLE_DISPLAY: Record<string, { label: string; initials: string; color: string; bg: string }> = {
  PO:          { label: 'Product Owner', initials: 'PO', color: 'text-purple-300', bg: 'bg-purple-600'  },
  ScrumMaster: { label: 'Scrum Master',  initials: 'SM', color: 'text-blue-300',   bg: 'bg-blue-600'    },
  Developer:   { label: 'Developer',     initials: 'DV', color: 'text-green-300',  bg: 'bg-green-600'   },
  QA:          { label: 'QA Engineer',   initials: 'QA', color: 'text-pink-300',   bg: 'bg-pink-600'    },
  DevOps:      { label: 'DevOps',        initials: 'DO', color: 'text-orange-300', bg: 'bg-orange-600'  },
  Architect:   { label: 'Architect',     initials: 'AR', color: 'text-indigo-300', bg: 'bg-indigo-600'  },
}

function AgentRow({ role, fsmState, activity }: { role: string; fsmState: string; activity: string }) {
  const { t } = useTranslation()
  const meta = ROLE_DISPLAY[role] ?? { label: role, initials: role.slice(0, 2).toUpperCase(), color: 'text-gray-300', bg: 'bg-gray-600' }
  const isActive = fsmState === 'active'
  const isError = fsmState === 'error'

  return (
    <div className="flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-surface-800/60 transition-colors">
      <div className={`w-7 h-7 ${meta.bg} rounded-md flex items-center justify-center text-[10px] font-bold text-white shrink-0`}>
        {ROLE_DISPLAY[role] ? t(`dashboard.roles.${role}.initials`, { defaultValue: meta.initials }) : meta.initials}
      </div>
      <div className="flex-1 min-w-0">
        <p className={`text-xs font-medium ${meta.color}`}>{ROLE_DISPLAY[role] ? t(`dashboard.roles.${role}.label`, { defaultValue: meta.label }) : meta.label}</p>
        {activity ? (
          <p className="text-[11px] text-gray-500 truncate">{activity}</p>
        ) : (
          <p className="text-[11px] text-gray-600 italic">{t('dashboard.idle', { defaultValue: 'idle' })}</p>
        )}
      </div>
      {isActive && <Loader2 size={12} className="text-emerald-400 animate-spin shrink-0" />}
      {isError  && <AlertTriangle size={12} className="text-red-400 shrink-0" />}
      {!isActive && !isError && (
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          fsmState === 'waiting' ? 'bg-brand-400' : 'bg-surface-600'
        }`} />
      )}
    </div>
  )
}

// ── Sprint Card ───────────────────────────────────────────────────────────────

function SprintCard({
  sprint, columns, total,
}: {
  sprint: any; columns: Record<string, any[]>; total: number
}) {
  const { t }   = useTranslation()
  const done    = columns.done?.length ?? 0
  const blocked = columns.blocked?.length ?? 0
  const inProg  = columns.in_progress?.length ?? 0

  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b border-surface-700/60">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h3 className="text-sm font-semibold text-white truncate">{sprint.sprint_name}</h3>
          <StatusBadge status={sprint.status} />
        </div>
        <div className="flex items-center gap-2">
          <ScopeBadge scope={sprint.scope_size} />
          {sprint.goal && (
            <p className="text-[11px] text-gray-500 truncate">{sprint.goal}</p>
          )}
        </div>
      </div>

      <div className="px-4 py-3 space-y-3">
        <ProgressBar done={done} total={total} />

        <div className="grid grid-cols-3 gap-2">
          {[
            { label: t('dashboard.inProgress', { defaultValue: 'In Progress' }), count: inProg,  color: 'text-brand-400'   },
            { label: t('dashboard.blocked', { defaultValue: 'Blocked' }), count: blocked, color: 'text-red-400'     },
            { label: t('dashboard.done', { defaultValue: 'Done' }), count: done,    color: 'text-emerald-400' },
          ].map(({ label, count, color }) => (
            <div key={label} className="text-center p-2 rounded-lg bg-surface-800/60">
              <p className={`text-lg font-bold tabular-nums ${color}`}>{count}</p>
              <p className="text-[10px] text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Quick Launch ──────────────────────────────────────────────────────────────

export function QuickLaunch({ onSuccess }: { onSuccess: (id: number) => void }) {
  const { t } = useTranslation()
  const [goal, setGoal] = useState('')
  const [scope, setScope] = useState<'S' | 'M' | 'L'>('M')
  const [plannedSprint, setPlannedSprint] = useState<SprintPlanResponse | null>(null)
  const [planSource, setPlanSource] = useState<'manual' | 'autonomous' | null>(null)
  // Blocked tasks of earlier sprints the person wants to try again here.
  const [carryOver, setCarryOver] = useState<number[]>([])
  const { companyId, companyName, setCompany } = useAppStore()
  const inbox = useInbox(companyId, false)
  const blockedTasks = (inbox.data?.blocked_tasks ?? []).filter(task => !task.frozen)
  // How earlier second attempts went, counted from the closed sprints' boards:
  // the evidence beside the ScrumMaster's advice when the person decides.
  const sprints = useSprints(blockedTasks.length > 0 ? companyId : null)
  const record = secondAttempts(sprints.data ?? [])
  // When a plan preview appears, start with the tasks the ScrumMaster's triage
  // recommends retrying, within the room the scope leaves; the person unticks
  // or adds from there. The triage is advice: nothing is sent without the tick.
  // Pre-ticked once per plan, so a later scope change or inbox refetch never
  // overwrites what the person chose.
  const pretickedPlan = useRef<SprintPlanResponse | null>(null)
  useEffect(() => {
    if (!plannedSprint) {
      pretickedPlan.current = null
      setCarryOver([])
      return
    }
    if (pretickedPlan.current === plannedSprint || !inbox.data) return
    pretickedPlan.current = plannedSprint
    const room = Math.max(0, SCOPE_META[scope].limit - plannedSprint.tasks.length)
    setCarryOver(
      inbox.data.blocked_tasks
        .filter(task => !task.frozen && task.triage?.decision === 'retry')
        .slice(0, room)
        .map(task => task.id),
    )
  }, [plannedSprint, inbox.data, scope])
  const initMutation    = useInitCompany()
  const planMutation    = usePlanSprint()
  const autoPlanMutation = usePlanSelfImprovementSprint()
  const sprintMutation  = useStartSprint()
  const navigate        = useNavigate()

  const busy  = initMutation.isPending || planMutation.isPending || autoPlanMutation.isPending || sprintMutation.isPending
  const error = sprintMutation.error ?? autoPlanMutation.error ?? planMutation.error ?? initMutation.error

  async function ensureCompany() {
    let cid = companyId

    if (!cid) {
      const resolvedCompanyName = companyName?.trim() || t('dashboard.demoCompany', { defaultValue: 'Fabrique Demo' })
      const company = await initMutation.mutateAsync({
        company_name: resolvedCompanyName,
        default_scope_size: scope,
      })
      cid = company.company_id
      setCompany(cid, resolvedCompanyName)
    }

    return cid
  }

  function resetPreview() {
    setPlannedSprint(null)
    setPlanSource(null)
    setCarryOver([])
  }

  async function generatePlan() {
    if (busy || !goal.trim()) return

    initMutation.reset()
    planMutation.reset()
    sprintMutation.reset()

    try {
      const cid = await ensureCompany()
      if (!cid) return

      const plan = await planMutation.mutateAsync({
        company_id: cid,
        prompt: goal.trim(),
        scope_size: scope,
      })

      setPlannedSprint(plan)
      setPlanSource('manual')
    } catch {
      return
    }
  }

  async function generateAutonomousPlan() {
    if (busy) return

    initMutation.reset()
    planMutation.reset()
    autoPlanMutation.reset()
    sprintMutation.reset()

    try {
      const cid = await ensureCompany()
      if (!cid) return

      const plan = await autoPlanMutation.mutateAsync({
        company_id: cid,
        scope_size: scope,
      })

      setPlannedSprint(plan)
      setPlanSource('autonomous')
    } catch {
      return
    }
  }

  async function launch() {
    if (busy || !plannedSprint) return

    initMutation.reset()
    planMutation.reset()
    autoPlanMutation.reset()
    sprintMutation.reset()

    try {
      const cid = await ensureCompany()
      if (!cid) return

      const sprint = await sprintMutation.mutateAsync({
        company_id: cid,
        sprint_name: plannedSprint.sprint_name,
        start_date: new Date().toISOString().split('T')[0],
        scope_size: scope,
        goal: plannedSprint.goal,
        backlog_items: plannedSprint.tasks,
        ...(carryOver.length > 0 ? { carry_over_ids: carryOver } : {}),
      })

      onSuccess(sprint.sprint_id)
      setGoal('')
      resetPreview()
      navigate(`/sprints/${sprint.sprint_id}/board`)
    } catch {
      return
    }
  }

  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={14} className="text-brand-400" />
        <h3 className="text-sm font-semibold text-gray-200">{t('dashboard.launchSprint', { defaultValue: 'Launch Sprint' })}</h3>
      </div>

      <textarea
        rows={2}
        value={goal}
        onChange={e => {
          setGoal(e.target.value)
          resetPreview()
        }}
        placeholder={t('dashboard.goalPlaceholder', { defaultValue: 'Describe the sprint goal…' })}
        className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 resize-none mb-3 transition-colors"
      />

      <div className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-surface-700 bg-surface-800/60 px-3 py-2">
        <div>
          <p className="text-xs font-medium text-gray-200">{t('dashboard.autonomousTitle', { defaultValue: 'Autonomous self-improvement' })}</p>
          <p className="text-[11px] text-gray-500">{t('dashboard.autonomousDescription', { defaultValue: 'Let the factory inspect the repo, preserve what already works, and propose the next Scrumban improvement sprint.' })}</p>
        </div>
        <button
          onClick={generateAutonomousPlan}
          disabled={busy}
          className="shrink-0 px-3 py-1.5 rounded-lg border border-brand-500/30 text-brand-300 text-xs font-medium hover:bg-brand-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {autoPlanMutation.isPending ? t('dashboard.scanning', { defaultValue: 'Scanning…' }) : t('dashboard.autoImprove', { defaultValue: 'Auto-Improve' })}
        </button>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-surface-700 overflow-hidden text-xs">
          {(['S', 'M', 'L'] as const).map(s => (
            <button
              key={s}
              title={t(`dashboard.scope.${s}.label`, { defaultValue: SCOPE_META[s].label })}
              onClick={() => {
                setScope(s)
                resetPreview()
              }}
              className={`px-3 py-1.5 font-medium transition-colors ${
                scope === s
                  ? 'bg-brand-600/20 text-brand-300 border-r border-brand-600/30 last:border-r-0'
                  : 'text-gray-500 hover:text-gray-300 border-r border-surface-700 last:border-r-0'
              }`}
            >
              {t(`dashboard.scope.${s}.short`, { defaultValue: s })}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-gray-600 flex-1">
          {t('dashboard.scopeSummary', {
            defaultValue: '{{scope}} · up to {{count}} tasks',
            scope: t(`dashboard.scope.${scope}.label`, { defaultValue: SCOPE_META[scope].label }),
            count: SCOPE_META[scope].limit,
          })}
        </span>
        {plannedSprint && (
          <button
            onClick={planSource === 'autonomous' ? generateAutonomousPlan : generatePlan}
            disabled={busy || (planSource !== 'autonomous' && !goal.trim())}
            className="px-3 py-1.5 rounded-lg border border-surface-700 text-gray-300 text-xs font-medium hover:border-brand-500/40 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {t('dashboard.regenerate', { defaultValue: 'Regenerate' })}
          </button>
        )}
        <button
          onClick={plannedSprint ? launch : generatePlan}
          disabled={busy || (!plannedSprint && !goal.trim())}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-brand-600 text-white text-xs font-semibold hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          {busy
            ? (planMutation.isPending
                ? t('dashboard.planning', { defaultValue: 'Planning…' })
                : t('dashboard.launching', { defaultValue: 'Launching…' }))
            : plannedSprint
              ? t('dashboard.launchSprint', { defaultValue: 'Launch Sprint' })
              : t('dashboard.generatePlan', { defaultValue: 'Generate Plan' })}
        </button>
      </div>

      {plannedSprint && (
        <div className="mt-3 rounded-lg border border-brand-500/20 bg-brand-950/10 p-3 space-y-3 animate-fade-in">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-brand-300/80">
                {planSource === 'autonomous'
                  ? t('dashboard.autonomousPreview', { defaultValue: 'Autonomous Plan Preview' })
                  : t('dashboard.planPreview', { defaultValue: 'Plan Preview' })}
              </p>
              <h4 className="text-sm font-semibold text-white mt-1">{plannedSprint.sprint_name}</h4>
            </div>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-semibold ${SCOPE_META[plannedSprint.scope_size].bg} ${SCOPE_META[plannedSprint.scope_size].color}`}>
              <Layers size={10} />
              {t(`dashboard.scope.${plannedSprint.scope_size}.label`, { defaultValue: SCOPE_META[plannedSprint.scope_size].label })}
            </span>
          </div>

          <p className="text-xs text-gray-400">{plannedSprint.goal}</p>

          {planSource === 'autonomous' && (
            <p className="text-[11px] text-brand-200/80">
              {t('dashboard.autonomousPlanDescription', { defaultValue: 'This plan was generated from repository context with a preserve-and-iterate rule: improve the next bottleneck, keep healthy assets, and move in bounded Scrumban slices.' })}
            </p>
          )}

          <div className="space-y-2">
            {plannedSprint.tasks.map((task, index) => (
              <div key={`${task.title}-${index}`} className="rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-gray-100">{index + 1}. {task.title}</p>
                    <p className="text-[11px] text-gray-500 mt-1">{task.description}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-[10px] uppercase tracking-wide text-brand-300">
                      {ROLE_DISPLAY[task.assignee]
                        ? t(`dashboard.roles.${task.assignee}.label`, { defaultValue: ROLE_DISPLAY[task.assignee].label })
                        : task.assignee}
                    </p>
                    <p className="text-[10px] text-gray-500 mt-1">
                      {t(`dashboard.priorities.${task.priority}`, { defaultValue: PRIORITY_LABELS[task.priority] ?? task.priority })}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {blockedTasks.length > 0 && (
            <fieldset className="space-y-1.5 rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
              <legend className="px-1 text-xs font-semibold text-gray-100">
                {t('dashboard.carryOverTitle', { defaultValue: 'Bring back blocked tasks' })}
              </legend>
              <p className="text-[11px] text-gray-500">
                {t('dashboard.carryOverHint', { defaultValue: 'Tasks the agents gave up on. Each one you tick gets a fresh attempt in this sprint, with what blocked it; they count towards the scope.' })}
              </p>
              {record.total > 0 && (
                <p className="text-[11px] text-gray-400">
                  {t('dashboard.carryOverRecord', {
                    done: record.done,
                    total: record.total,
                    briefedDone: record.briefed_done,
                    briefed: record.briefed,
                    defaultValue: "So far {{done}} of {{total}} second attempts got done; with the ScrumMaster's brief, {{briefedDone}} of {{briefed}}.",
                  })}
                </p>
              )}
              {blockedTasks.map(task => (
                <label key={task.id} className="flex items-start gap-2 text-xs text-gray-300">
                  <input type="checkbox" className="mt-0.5" checked={carryOver.includes(task.id)}
                    disabled={!carryOver.includes(task.id) && plannedSprint.tasks.length + carryOver.length >= SCOPE_META[scope].limit}
                    onChange={e => setCarryOver(ids => e.target.checked ? [...ids, task.id] : ids.filter(id => id !== task.id))} />
                  <span className="min-w-0">
                    {t('dashboard.carryOverTask', { title: task.title, sprint: task.sprint_name, defaultValue: '{{title}} · {{sprint}}' })}
                    {task.triage && (
                      // The ScrumMaster's answer to the escalation: a claim for the person to weigh.
                      <span className="block text-[11px] text-sky-200/80">
                        {task.triage.decision === 'retry'
                          ? t('dashboard.carryOverTriageRetry', { why: task.triage.why, defaultValue: 'ScrumMaster: another attempt. {{why}}' })
                          : t('dashboard.carryOverTriagePerson', { why: task.triage.why, defaultValue: 'ScrumMaster: leave it for a person. {{why}}' })}
                      </span>
                    )}
                  </span>
                </label>
              ))}
              {plannedSprint.tasks.length + carryOver.length >= SCOPE_META[scope].limit && carryOver.length < blockedTasks.length && (
                <p className="text-[11px] text-amber-300">{t('dashboard.carryOverFull', { defaultValue: 'The scope is full: untick a task or pick a larger scope.' })}</p>
              )}
            </fieldset>
          )}

          <p className="text-[11px] text-gray-500">
            {t('dashboard.reviewPlan', { defaultValue: 'Review the plan, regenerate if needed, then launch the sprint.' })}
          </p>
        </div>
      )}

      {error && (
        <p className="mt-2 text-[11px] text-red-400 flex items-center gap-1">
          <AlertTriangle size={11} /> {error instanceof Error ? error.message : t('dashboard.launchFailed', { defaultValue: 'Launch failed' })}
        </p>
      )}
    </div>
  )
}

function QuotaWidget({ companyId }: { companyId: number | null }) {
  const { t } = useTranslation()
  const { data } = useQuotas(companyId)
  const quotas = Array.isArray(data) ? data : []
  const totalUsed = quotas.reduce((s: number, q: any) => s + (q.token_quota_used || 0), 0)
  const totalLimit = quotas.reduce((s: number, q: any) => s + (q.token_quota_limit || 0), 0)
  if (!totalLimit) return null
  const pct = Math.min(100, Math.round((totalUsed / totalLimit) * 100))
  const color = pct >= 90 ? 'text-red-400' : pct >= 70 ? 'text-yellow-400' : 'text-emerald-400'
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-surface-700 bg-surface-900 text-[11px] font-medium text-gray-300">
      <span className={color}>⚡ {t('dashboard.tokenUsage', { used: totalUsed.toLocaleString(), limit: totalLimit.toLocaleString(), defaultValue: '{{used}} / {{limit}} tokens' })}</span>
      <span className="text-gray-500">({pct}%)</span>
    </div>
  )
}

// ── Sprint Overview ───────────────────────────────────────────────────────────

export default function SprintOverview({ sprintId }: { sprintId: number | null }) {
  const { t } = useTranslation()
  const { setActiveSprint, companyId, companyName } = useAppStore()
  const { data: board, isLoading: boardLoading } = useSprintBoard(sprintId)
  const { data: analytics } = useAnalyticsSummary(sprintId)
  const { data: quotaData } = useQuotas(companyId)
  const connectToSprintStream = useAgentStore(s => s.connect)
  const disconnectFromSprintStream = useAgentStore(s => s.disconnect)
  const agentStates = useAgentStore(s => s.agentStates)
  const isSSEConnected = useAgentStore(s => s.isConnected)

  useEffect(() => {
    if (!sprintId) return
    connectToSprintStream(String(sprintId))
    return () => {
      disconnectFromSprintStream()
    }
  }, [sprintId, connectToSprintStream, disconnectFromSprintStream])

  const sprint  = board?.sprint
  const columns = board?.columns ?? {}
  const total   = board?.total ?? 0
  const done    = columns.done?.length ?? 0
  const blocked = columns.blocked?.length ?? 0
  const inProg  = columns.in_progress?.length ?? 0

  const healthScore    = analytics?.health_score ?? null
  const needsSplit     = sprint?.status === 'needs_split'

  const activeAgentCount  = Object.values(agentStates).filter(a => a.fsmState === 'active').length
  const visibleAgents     = Object.entries(agentStates)
  const hasAgents         = visibleAgents.length > 0

  return (
    <div className="min-w-0">
      <div className="space-y-5">

        {/* ── Overview header ───────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-bold text-white tracking-tight">
              {companyName ? `${companyName}` : t('dashboard.title', { defaultValue: 'La Fabrique' })}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {t('dashboard.commandCenter', { defaultValue: 'AI Sprint command center' })}
              {sprint && (
                <> · <span className="text-gray-400">{sprint.sprint_name}</span></>
              )}
            </p>
          </div>
          <QuotaWidget companyId={companyId} />
        </div>

        {/* ── Quota alert ────────────────────────────────────────────── */}
        {Array.isArray(quotaData) && quotaData.some((q: any) => q.limit > 0 && (q.used / q.limit) >= 0.8) && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-2 text-sm text-yellow-200">
            <AlertTriangle size={16} />
            <span>{t('dashboard.quotaAlert', { defaultValue: 'Token quota is above 80% for one or more business units. Consider resetting or increasing limits.' })}</span>
            <Link to="/company/quotas" className="ml-auto text-yellow-300 underline text-xs">{t('dashboard.manageQuotas', { defaultValue: 'Manage quotas' })}</Link>
          </div>
        )}

        {/* ── KPI strip ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <KpiCard
            icon={Target}
            label={t('dashboard.sprintTasks', { defaultValue: 'Sprint Tasks' })}
            value={total}
            sub={sprint ? sprint.sprint_name : t('dashboard.noActiveSprint', { defaultValue: 'No active sprint' })}
          />
          <KpiCard
            icon={CheckCircle2}
            label={t('dashboard.completed', { defaultValue: 'Completed' })}
            value={done}
            sub={total > 0 ? t('dashboard.percentDone', { defaultValue: '{{percent}}% done', percent: Math.round((done / total) * 100) }) : '—'}
            accent
          />
          <KpiCard
            icon={CircleDot}
            label={t('dashboard.blocked', { defaultValue: 'Blocked' })}
            value={blocked}
            sub={blocked > 0 ? t('dashboard.needsAttention', { defaultValue: 'Needs attention' }) : t('dashboard.clear', { defaultValue: 'Clear' })}
            warn={blocked > 0}
          />
          <KpiCard
            icon={Bot}
            label={t('dashboard.agentsWorking', { defaultValue: 'Agents Working' })}
            value={activeAgentCount}
            sub={isSSEConnected ? t('dashboard.streamConnected', { defaultValue: 'Live stream connected' }) : t('dashboard.disconnected', { defaultValue: 'Disconnected' })}
            accent={activeAgentCount > 0}
          />
          <KpiCard
            icon={Zap}
            label={t('dashboard.healthScore', { defaultValue: 'Health Score' })}
            value={healthScore !== null ? `${healthScore}` : '—'}
            sub={healthScore !== null
              ? (healthScore >= 80 ? t('dashboard.sprintHealthy', { defaultValue: 'Sprint healthy' }) : t('dashboard.reviewNeeded', { defaultValue: 'Review needed' }))
              : t('dashboard.noHealthData', { defaultValue: 'No data yet' })}
            accent={healthScore !== null && healthScore >= 80}
            warn={healthScore !== null && healthScore < 60}
          />
        </div>

        {/* ── Needs Split alert ─────────────────────────────────────── */}
        {needsSplit && sprint && sprintId && (
          <NeedsSplitAlert sprintId={sprintId} sprintName={sprint.sprint_name} />
        )}

        {/* ── Main grid ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Sprint card — takes 2 cols */}
          <div className="lg:col-span-2 space-y-4">
            {boardLoading ? (
              <LoadingSkeleton message={t('dashboard.loadingSprint', { defaultValue: 'Loading sprint data...' })} />
            ) : sprint && sprintId ? (
              <>
                <SprintCard sprint={sprint} columns={columns} total={total} />
                <SprintHealthChart
                  total={total}
                  done={done}
                  inProgress={inProg}
                  blocked={blocked}
                  healthScore={healthScore}
                />
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-surface-700 bg-surface-900/40 p-8 text-center">
                <Cpu size={28} className="text-gray-600 mx-auto mb-3" />
                <p className="text-sm font-medium text-gray-400">{t('dashboard.noActiveSprint', { defaultValue: 'No active sprint' })}</p>
                <p className="text-xs text-gray-600 mt-1">{t('dashboard.launchHint', { defaultValue: 'Launch a sprint below to start working with your agents' })}</p>
              </div>
            )}

            {/* Quick launch */}
            <QuickLaunch onSuccess={id => setActiveSprint(id)} />
          </div>

          {/* Right column: agent roster + system status */}
          <div className="space-y-4">
            {/* Agent Roster */}
            <div className="rounded-xl border border-surface-700 bg-surface-900">
              <div className="flex items-center justify-between px-3 py-2.5 border-b border-surface-700/60">
                <div className="flex items-center gap-1.5">
                  <Bot size={13} className="text-brand-400" />
                  <span className="text-xs font-semibold text-gray-300">{t('dashboard.agentRoster', { defaultValue: 'Agent Roster' })}</span>
                </div>
                {hasAgents && (
                  <span className="text-[10px] text-gray-500">{t('dashboard.agentCount', { defaultValue: '{{count}} agents', count: visibleAgents.length })}</span>
                )}
              </div>

              <div className="py-1">
                {hasAgents ? (
                  visibleAgents.map(([role, state]) => (
                    <AgentRow
                      key={role}
                      role={role}
                      fsmState={state.fsmState}
                      activity={state.currentActivity}
                    />
                  ))
                ) : (
                  <div className="px-3 py-4 text-center">
                    <p className="text-[11px] text-gray-600">{t('dashboard.noAgents', { defaultValue: 'No agents seen yet.' })}</p>
                    <p className="text-[11px] text-gray-600 mt-0.5">{t('dashboard.activateAgents', { defaultValue: 'Launch a sprint to activate agents.' })}</p>
                  </div>
                )}
              </div>

              <div className="px-3 pb-2.5 pt-1 border-t border-surface-700/60">
                <Link
                  to="/agents"
                  className="flex items-center gap-1 text-[11px] text-brand-400 hover:text-brand-300 transition-colors"
                >
                  <Settings2 size={10} />
                  {t('dashboard.manageAgents', { defaultValue: 'Manage agents' })} <ChevronRight size={10} />
                </Link>
              </div>
            </div>

            {/* System Status */}
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-3">
              <div className="flex items-center gap-1.5 mb-3">
                <ShieldAlert size={13} className="text-gray-400" />
                <span className="text-xs font-semibold text-gray-300">{t('dashboard.system', { defaultValue: 'System' })}</span>
              </div>
              <div className="space-y-2">
                {[
                  { label: t('dashboard.agentStream', { defaultValue: 'Agent Stream' }), ok: isSSEConnected },
                ].map(({ label, ok }) => (
                  <div key={label} className="flex items-center justify-between text-[11px]">
                    <span className="text-gray-500">{label}</span>
                    <span className={`flex items-center gap-1 font-medium ${ok ? 'text-emerald-400' : 'text-gray-600'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-surface-600'}`} />
                      {ok ? t('dashboard.online', { defaultValue: 'Online' }) : t('dashboard.offline', { defaultValue: 'Offline' })}
                    </span>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
