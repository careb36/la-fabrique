/**
 * GlassRoom — enterprise agents room.
 *
 * Three-column layout: agent sidebar → message feed → detail panel.
 * Slack-style message grouping with rich type differentiation.
 * Handles needs_split events as first-class citizens.
 */

import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import i18n from '../i18n'
import { useAgentStore, AgentMessage, type SprintRetro } from '../store/agentStore'
import { useSprintBoard, useQuotas } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import type { BacklogItem } from '../services/api'
import {
  AlertTriangle, Bot, Check, ChevronDown, ChevronRight,
  Copy, Eye, GitBranch, Hash, HeartPulse, Layers, Loader2, RotateCcw, Search,
  ShieldAlert, SplitSquareVertical, X, ZapOff,
} from 'lucide-react'

/** The task page that shows a backlog item and the deliverables agents attached to it. */
function taskPath(sprintId: string, taskId: number) {
  return `/sprints/${sprintId}/tasks/${taskId}`
}

// ── Agent identity ────────────────────────────────────────────────────────────

interface AgentIdentity {
  initials: string
  bg: string
  ring: string
  label: string
  color: string
}

const AGENTS: Record<string, AgentIdentity> = {
  PO:           { initials: 'PO', bg: 'bg-purple-600',  ring: 'ring-purple-400/30', label: 'Product Owner',  color: 'text-purple-300'  },
  Architect:    { initials: 'AR', bg: 'bg-indigo-600',  ring: 'ring-indigo-400/30', label: 'Architect',      color: 'text-indigo-300'  },
  ScrumMaster:  { initials: 'SM', bg: 'bg-blue-600',    ring: 'ring-blue-400/30',   label: 'Scrum Master',   color: 'text-blue-300'    },
  Developer:    { initials: 'DV', bg: 'bg-green-600',   ring: 'ring-green-400/30',  label: 'Developer',      color: 'text-green-300'   },
  Dev:          { initials: 'DV', bg: 'bg-green-600',   ring: 'ring-green-400/30',  label: 'Developer',      color: 'text-green-300'   },
  Backend:      { initials: 'BE', bg: 'bg-cyan-600',    ring: 'ring-cyan-400/30',   label: 'Backend Dev',    color: 'text-cyan-300'    },
  Frontend:     { initials: 'FE', bg: 'bg-yellow-600',  ring: 'ring-yellow-400/30', label: 'Frontend Dev',   color: 'text-yellow-300'  },
  QA:           { initials: 'QA', bg: 'bg-pink-600',    ring: 'ring-pink-400/30',   label: 'QA Engineer',    color: 'text-pink-300'    },
  DevOps:       { initials: 'DO', bg: 'bg-orange-600',  ring: 'ring-orange-400/30', label: 'DevOps',         color: 'text-orange-300'  },
  Data:         { initials: 'DA', bg: 'bg-teal-600',    ring: 'ring-teal-400/30',   label: 'Data Engineer',  color: 'text-teal-300'    },
  DataEngineer: { initials: 'DA', bg: 'bg-teal-600',    ring: 'ring-teal-400/30',   label: 'Data Engineer',  color: 'text-teal-300'    },
  System:       { initials: '⚙',  bg: 'bg-gray-600',    ring: 'ring-gray-400/30',   label: 'System',         color: 'text-gray-400'    },
}

const FALLBACK_AGENT: AgentIdentity = {
  initials: 'AI', bg: 'bg-brand-600', ring: 'ring-brand-400/30', label: 'Agent', color: 'text-brand-300',
}

const ACTIVE_AGENT_TTL_MS = 90_000
const FRESH_ACTIVITY_MS = 12_000

function getAgent(key: string): AgentIdentity {
  return (
    AGENTS[key] ??
    AGENTS[Object.keys(AGENTS).find(k => k.toLowerCase() === key?.toLowerCase()) ?? ''] ??
    FALLBACK_AGENT
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// Memoized date formatters to avoid repeated Intl.DateTimeFormat instantiation
const _timeFormatter = new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', hour12: true })
const _dateFormatters = new Map<string, Intl.DateTimeFormat>()

// Module-level cache for reference date strings to avoid re-instantiating
// new Date() on every formatDate call (high-frequency render path).
let _todayStr = new Date().toDateString()
let _yesterdayStr = new Date(Date.now() - 86400000).toDateString()

// Periodic update to handle day rollovers (every 60s).
if (typeof window !== 'undefined') {
  setInterval(() => {
    const now = new Date()
    _todayStr = now.toDateString()
    _yesterdayStr = new Date(now.getTime() - 86400000).toDateString()
  }, 60000)
}

function _getDateFormatter(lang: string): Intl.DateTimeFormat {
  if (!_dateFormatters.has(lang)) {
    _dateFormatters.set(lang, new Intl.DateTimeFormat(lang || 'en', { weekday: 'long', month: 'long', day: 'numeric' }))
  }
  return _dateFormatters.get(lang)!
}

function formatTime(iso: string): string {
  try {
    return _timeFormatter.format(new Date(iso))
  } catch { return '' }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    const dStr = d.toDateString()

    if (dStr === _todayStr) return i18n.t('glassroom.today', 'Today')
    if (dStr === _yesterdayStr) return i18n.t('glassroom.yesterday', 'Yesterday')

    return _getDateFormatter(i18n.language || 'en').format(d)
  } catch { return '' }
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`
}

function formatAgeShort(ms: number): string {
  if (ms < 1000) return '0s'
  return formatElapsed(ms)
}

function parseCooldownUntil(detail?: string): string | undefined {
  if (!detail) return undefined
  const match = detail.match(/cooldown_until=([^\s]+)/)
  return match?.[1]
}

function hasDeliverableComment(comment: { author: string; text: string; created_at: string }): boolean {
  const text = (comment.text || '').trim()
  if (!text || comment.author === 'System') return false
  if (text.toUpperCase().startsWith('APPROVED:') || text.toUpperCase().startsWith('NEEDS WORK:')) return false
  return true
}

function extractBlockedReason(comments: BacklogItem['comments'] | undefined): string | undefined {
  const entries = comments || []
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const text = (entries[index]?.text || '').trim()
    if (!text) continue
    const lowered = text.toLowerCase()
    if (
      lowered.includes('manual triage') ||
      lowered.includes('quality gate failed') ||
      lowered.includes('agent error:') ||
      lowered.includes('missing deliverable') ||
      lowered.includes('freeze after')
    ) {
      return text
    }
  }
  return undefined
}

function phaseLabel(t: (key: string, opts?: Record<string, unknown>) => string, phase?: string): string {
  const labels: Record<string, string> = {
    queued: 'Queued',
    claimed: 'Claimed',
    context: 'Context',
    memory_retrieved: 'Memory retrieved',
    execution: 'Execution',
    deliverable: 'Deliverable',
    artifact_generation: 'Artifacts',
    qa_handoff: 'QA handoff',
    qa_review: 'QA review',
    qa_approved: 'Approved',
    rework: 'Rework',
    retry: 'Retry',
    restart_recovery: 'Restart recovery',
    blocked_recovery: 'Blocked recovery',
    quality_gate: 'Quality gate',
    qa_gate: 'QA gate',
    implementation_complete: 'Implementation complete',
    kickoff_complete: 'Kickoff complete',
    architect_consult: 'Architect consult',
    todo_recovery: 'Todo recovery',
    unknown: 'Unknown',
  }
  const key = phase || 'unknown'
  return t(`glassroom.phaseLabels.${key}`, { defaultValue: labels[key] ?? phase ?? 'Unknown' })
}

function renderInlineMarkdown(text: string): Array<string | JSX.Element> {
  const parts: Array<string | JSX.Element> = []
  const pattern = /\*\*(.+?)\*\*/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    parts.push(
      <strong key={`bold-${match.index}`} className="font-semibold text-gray-100">
        {match[1]}
      </strong>,
    )
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts.length > 0 ? parts : [text]
}

function MessageContent({ text, isError }: { text: string; isError: boolean }) {
  return (
    <div className={`text-[13px] break-words leading-relaxed ${isError ? 'text-red-300' : 'text-gray-200'}`}>
      {text.split('\n').map((line, index) => (
        <p key={`${index}-${line.slice(0, 12)}`} className={index === 0 ? '' : 'mt-1'}>
          {line.length > 0 ? renderInlineMarkdown(line) : <span>&nbsp;</span>}
        </p>
      ))}
    </div>
  )
}

interface MessageGroup {
  agent: string
  identity: AgentIdentity
  timestamp: string
  messages: AgentMessage[]
}

interface AssistantSummaryEntry {
  label: string
  used: number
  quotaSkips: number
  failures: number
  unavailableSkips: number
  requested: number
  cooldownUntil?: string
  lastDecision?: string
}

interface HealthPanelEntry {
  label: string
  value: string
  tone: 'neutral' | 'good' | 'warn' | 'danger'
}

interface QuotaTelemetry {
  quota: number
  used: number
  remaining: number
  ratio: number
}

interface SprintTaskEntry {
  id: number
  title: string
  status: BacklogItem['status']
  priority: BacklogItem['priority']
  assignee?: string
  comments?: BacklogItem['comments']
}

interface TaskAutonomyEntry {
  id: number
  title: string
  status: BacklogItem['status']
  priority: BacklogItem['priority']
  assignee?: string
  currentPhase: string
  reworkCount: number
  reviewCount: number
  deliverableCount: number
  blockedReason?: string
  assistantLabels: string[]
  stepStates: Array<{
    key: string
    label: string
    state: 'pending' | 'active' | 'done' | 'blocked'
    detail?: string
  }>
}

function groupMessages(messages: AgentMessage[]): { date: string; groups: MessageGroup[] }[] {
  const dayMap = new Map<string, AgentMessage[]>()
  for (const msg of messages) {
    const dateKey = msg.timestamp ? new Date(msg.timestamp).toDateString() : 'Unknown'
    if (!dayMap.has(dateKey)) dayMap.set(dateKey, [])
    dayMap.get(dateKey)!.push(msg)
  }

  const result: { date: string; groups: MessageGroup[] }[] = []
  for (const [, dayMsgs] of dayMap) {
    const groups: MessageGroup[] = []
    let current: MessageGroup | null = null
    for (const msg of dayMsgs) {
      const agentKey = msg.agent || msg.role || 'System'
      if (current && current.agent === agentKey) {
        current.messages.push(msg)
      } else {
        current = {
          agent: agentKey,
          identity: getAgent(agentKey),
          timestamp: msg.timestamp,
          messages: [msg],
        }
        groups.push(current)
      }
    }
    result.push({ date: formatDate(dayMsgs[0]?.timestamp || ''), groups })
  }
  return result
}

function getEventTypes(t: (key: string, opts?: Record<string, unknown>) => string) {
  return [
    { value: '', label: t('glassroom.eventTypes.all', { defaultValue: 'All types' }) },
    { value: 'message', label: t('glassroom.eventTypes.message', { defaultValue: 'Message' }) },
    { value: 'agent_start', label: t('glassroom.eventTypes.working', { defaultValue: 'Working' }) },
    { value: 'agent_complete', label: t('glassroom.eventTypes.delivered', { defaultValue: 'Delivered' }) },
    { value: 'status', label: t('glassroom.eventTypes.status', { defaultValue: 'Status' }) },
    { value: 'error', label: t('glassroom.eventTypes.error', { defaultValue: 'Error' }) },
  ] as const
}

// ── Atoms ─────────────────────────────────────────────────────────────────────

function AgentAvatar({ identity, size = 'md' }: { identity: AgentIdentity; size?: 'sm' | 'md' | 'lg' }) {
  const dims = { sm: 'w-5 h-5 text-[9px]', md: 'w-8 h-8 text-xs', lg: 'w-10 h-10 text-sm' }[size]
  return (
    <div className={`${dims} ${identity.bg} ${identity.ring} ring-2 rounded-lg flex items-center justify-center font-bold text-white shrink-0 select-none`}>
      {identity.initials}
    </div>
  )
}

function TypeBadge({ type }: { type: string }) {
  const { t } = useTranslation()
  const cfg: Record<string, { label: string; cls: string; spin?: boolean }> = {
    agent_start:    { label: t('glassroom.badgeLabels.working', 'working'),   cls: 'bg-brand-500/15 text-brand-300 border-brand-500/25',     spin: true  },
    agent_complete: { label: t('glassroom.badgeLabels.delivered', 'delivered'), cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'             },
    error:          { label: t('glassroom.badgeLabels.error', 'error'),     cls: 'bg-red-500/15 text-red-300 border-red-500/25'                         },
    status:         { label: t('glassroom.badgeLabels.update', 'update'),    cls: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/25'                },
    needs_split:    { label: t('glassroom.badgeLabels.split', 'split'),     cls: 'bg-amber-500/15 text-amber-300 border-amber-500/25'                   },
  }
  const c = cfg[type]
  if (!c) return null
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${c.cls}`}>
      {c.spin && <Loader2 size={9} className="animate-spin" />}
      {type === 'error' && <AlertTriangle size={9} />}
      {type === 'needs_split' && <SplitSquareVertical size={9} />}
      {c.label}
    </span>
  )
}

function CopyBtn({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={copy}
      className="opacity-0 group-hover/msg:opacity-100 transition-opacity p-1 rounded hover:bg-white/10"
      title={t('glassroom.copy')}
    >
      {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} className="text-gray-500" />}
    </button>
  )
}

function PreviewCard({ preview, task }: { preview: string; task?: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  if (!preview) return null
  return (
    <div className="mt-1.5 rounded-lg border border-surface-600/60 bg-surface-800/60 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 w-full text-left px-3 py-1.5 hover:bg-surface-700/40 transition-colors"
      >
        {open ? <ChevronDown size={11} className="text-gray-500" /> : <ChevronRight size={11} className="text-gray-500" />}
        <Eye size={11} className="text-brand-400" />
        <span className="text-[11px] text-gray-400 font-medium truncate flex-1">{task || t('glassroom.viewDeliverable', { defaultValue: 'View deliverable' })}</span>
      </button>
      {open && (
        <div className="px-3 pb-2.5 pt-1 border-t border-surface-700/50">
          <pre className="text-[11px] text-gray-300 whitespace-pre-wrap break-words font-mono leading-relaxed max-h-48 overflow-y-auto">
            {preview}
          </pre>
        </div>
      )}
    </div>
  )
}

function AssistantBadge({ msg }: { msg: AgentMessage }) {
  const { t } = useTranslation()
  if (!msg.assistantLabel) return null

  const palette = msg.assistantLabel.includes('Claude')
    ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
    : 'border-sky-500/30 bg-sky-500/10 text-sky-200'

  const decisionTone: Record<string, string> = {
    used: 'text-emerald-300',
    requested: 'text-sky-300',
    skipped_quota_cooldown: 'text-amber-300',
    quota_cooldown: 'text-amber-300',
    unavailable: 'text-gray-400',
    failed: 'text-red-300',
  }

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px]">
      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-semibold ${palette}`}>
        {msg.assistantLabel}
      </span>
      {msg.assistantPurpose && (
        <span className="text-gray-400">{msg.assistantPurpose}</span>
      )}
      {msg.assistantDecision && (
        <span className={decisionTone[msg.assistantDecision] ?? 'text-gray-400'}>
          {t(`glassroom.assistantDecisions.${msg.assistantDecision}`, { defaultValue: msg.assistantDecision.split('_').join(' ') })}
        </span>
      )}
    </div>
  )
}

function AssistantSummaryPanel({ entries }: { entries: AssistantSummaryEntry[] }) {
  const { t } = useTranslation()
  if (entries.length === 0) return null

  return (
    <div className="border-b border-surface-700/60 p-3 space-y-2">
      <div>
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
          {t('glassroom.assistantSummaryTitle')}
        </p>
        <p className="text-[11px] text-gray-500 mt-1">
          {t('glassroom.assistantSummarySubtitle')}
        </p>
      </div>

      <div className="space-y-2">
        {entries.map(entry => {
          const pillTone = entry.label.includes('Claude')
            ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
            : 'border-sky-500/30 bg-sky-500/10 text-sky-200'

          return (
            <div key={entry.label} className="rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${pillTone}`}>
                  {entry.label}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-[10px]">
                <div className="rounded-md bg-emerald-500/10 px-2 py-1.5 text-emerald-300">
                  <p className="text-[9px] uppercase tracking-wider text-emerald-400/80">{t('glassroom.assistantUsed')}</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{entry.used}</p>
                </div>
                <div className="rounded-md bg-amber-500/10 px-2 py-1.5 text-amber-300">
                  <p className="text-[9px] uppercase tracking-wider text-amber-400/80">{t('glassroom.assistantQuotaSkips')}</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{entry.quotaSkips}</p>
                </div>
                <div className="rounded-md bg-red-500/10 px-2 py-1.5 text-red-300">
                  <p className="text-[9px] uppercase tracking-wider text-red-400/80">{t('glassroom.assistantFailures')}</p>
                  <p className="mt-1 text-sm font-semibold tabular-nums">{entry.failures}</p>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-gray-500">
                <span>{t('glassroom.assistantRequested', { count: entry.requested, defaultValue: 'requested {{count}}' })}</span>
                <span>{t('glassroom.assistantUnavailable', { count: entry.unavailableSkips, defaultValue: 'unavailable {{count}}' })}</span>
                {entry.cooldownUntil && <span>{t('glassroom.assistantCooldown', { time: formatTime(entry.cooldownUntil), defaultValue: 'cooldown until {{time}}' })}</span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SprintTaskPanel({ tasks, sprintId }: { tasks: SprintTaskEntry[]; sprintId: string }) {
  const { t } = useTranslation()
  if (tasks.length === 0) return null

  const statusTone: Record<SprintTaskEntry['status'], string> = {
    todo: 'bg-surface-800 text-gray-300',
    in_progress: 'bg-blue-500/10 text-blue-300',
    in_review: 'bg-amber-500/10 text-amber-300',
    done: 'bg-emerald-500/10 text-emerald-300',
    blocked: 'bg-red-500/10 text-red-300',
  }

  const priorityTone: Record<SprintTaskEntry['priority'], string> = {
    low: 'text-gray-500',
    medium: 'text-sky-300',
    high: 'text-amber-300',
    critical: 'text-red-300',
  }

  return (
    <div className="border-b border-surface-700/60 p-3 space-y-2">
      <div>
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
          {t('glassroom.taskSummaryTitle')}
        </p>
        <p className="text-[11px] text-gray-500 mt-1">
          {t('glassroom.taskSummarySubtitle')}
        </p>
      </div>

      <div className="space-y-2">
        {tasks.map(task => (
          <div key={task.id} className="rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
            <div className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <Link
                  to={taskPath(sprintId, task.id)}
                  className="block text-[11px] font-medium text-gray-200 leading-tight break-words hover:text-brand-300 hover:underline"
                >
                  {task.title}
                </Link>
                <div className="mt-1 flex items-center gap-2 flex-wrap text-[10px]">
                  <span className={`rounded-full px-1.5 py-0.5 font-medium ${statusTone[task.status]}`}>
                    {t(`glassroom.taskStatus.${task.status}`)}
                  </span>
                  <span className={priorityTone[task.priority]}>
                    {t('glassroom.taskPriority')}: {t(`glassroom.taskPriorityValue.${task.priority}`)}
                  </span>
                </div>
              </div>
            </div>
            <p className="mt-1.5 text-[10px] text-gray-500">
              {t('glassroom.taskOwner')}: {task.assignee || t('glassroom.unassigned')}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

function HealthPanel({ entries }: { entries: HealthPanelEntry[] }) {
  const { t } = useTranslation()
  if (entries.length === 0) return null

  const toneClass: Record<HealthPanelEntry['tone'], string> = {
    neutral: 'bg-surface-800 text-gray-300',
    good: 'bg-emerald-500/10 text-emerald-300',
    warn: 'bg-amber-500/10 text-amber-300',
    danger: 'bg-red-500/10 text-red-300',
  }

  return (
    <div className="border-b border-surface-700/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <HeartPulse size={12} className="text-emerald-400" />
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
          {t('glassroom.healthTitle', 'Operational Health')}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
        {entries.map(entry => (
          <div key={entry.label} className="rounded-lg border border-surface-700 bg-surface-900/70 px-3 py-2.5 min-w-0">
            <p className="text-[9px] uppercase tracking-wider text-gray-500">{entry.label}</p>
            <p className={`mt-2 inline-flex rounded-full px-2 py-1 text-[10px] font-medium ${toneClass[entry.tone]}`}>
              {entry.value}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

function QuotaTelemetryPanel({ quota }: { quota?: QuotaTelemetry }) {
  const { t } = useTranslation()
  if (!quota || quota.quota <= 0) return null

  const percent = Math.round(quota.ratio * 100)
  const barTone = percent >= 90 ? 'bg-red-400' : percent >= 70 ? 'bg-amber-400' : 'bg-emerald-400'

  return (
    <div className="border-b border-surface-700/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <ShieldAlert size={12} className="text-sky-300" />
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
          {t('glassroom.quotaTitle', 'Quota Telemetry')}
        </p>
      </div>
      <div className="rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
        <div className="flex items-center justify-between text-[10px] text-gray-400">
          <span>{t('glassroom.quotaUsed', 'Used')}</span>
          <span className="tabular-nums">{quota.used} / {quota.quota}</span>
        </div>
        <div className="mt-2 h-2 rounded-full bg-surface-800 overflow-hidden">
          <div className={`h-full ${barTone}`} style={{ width: `${Math.max(4, percent)}%` }} />
        </div>
        <div className="mt-2 flex items-center justify-between text-[10px] text-gray-500">
          <span>{percent}%</span>
          <span>{t('glassroom.quotaRemaining', 'Remaining')}: {quota.remaining}</span>
        </div>
      </div>
    </div>
  )
}

function TaskAutonomyTree({ tasks }: { tasks: TaskAutonomyEntry[] }) {
  const { t } = useTranslation()
  if (tasks.length === 0) return null

  const stateTone: Record<TaskAutonomyEntry['stepStates'][number]['state'], string> = {
    pending: 'bg-surface-800 text-gray-500',
    active: 'bg-sky-500/10 text-sky-300',
    done: 'bg-emerald-500/10 text-emerald-300',
    blocked: 'bg-red-500/10 text-red-300',
  }

  return (
    <div className="border-b border-surface-700/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <GitBranch size={12} className="text-violet-300" />
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">
          {t('glassroom.autonomyTreeTitle', 'Autonomy Tree')}
        </p>
      </div>
      <div className="space-y-2">
        {tasks.map(task => (
          <div key={task.id} className="rounded-lg border border-surface-700 bg-surface-900/70 p-2.5">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-medium text-gray-200 break-words">{task.title}</p>
                <p className="mt-1 text-[10px] text-gray-500">
                  {phaseLabel(t, task.currentPhase)} · {t('glassroom.reworksCount', { n: task.reworkCount, defaultValue: '{{n}} reworks' })} · {t('glassroom.qaReviewsCount', { n: task.reviewCount, defaultValue: '{{n}} QA reviews' })}
                </p>
              </div>
              <span className="text-[10px] text-gray-500">#{task.id}</span>
            </div>
            <div className="mt-2 space-y-1.5">
              {task.stepStates.map(step => (
                <div key={step.key} className="flex items-start gap-2">
                  <span className={`mt-0.5 h-2 w-2 rounded-full ${
                    step.state === 'done' ? 'bg-emerald-400' :
                    step.state === 'active' ? 'bg-sky-400' :
                    step.state === 'blocked' ? 'bg-red-400' : 'bg-surface-700'
                  }`} />
                  <div className="min-w-0 flex-1">
                    <span className={`inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-medium ${stateTone[step.state]}`}>
                      {step.label}
                    </span>
                    {step.detail && <p className="mt-1 text-[10px] text-gray-500 break-words">{step.detail}</p>}
                  </div>
                </div>
              ))}
            </div>
            {(task.blockedReason || task.assistantLabels.length > 0) && (
              <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-gray-500">
                {task.assistantLabels.map(label => (
                  <span key={label} className="rounded-full border border-surface-700 px-1.5 py-0.5">{label}</span>
                ))}
                {task.blockedReason && <span className="text-red-300">{task.blockedReason}</span>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function DateSeparator({ date }: { date: string }) {
  return (
    <div className="flex items-center gap-3 py-2 px-4">
      <div className="flex-1 h-px bg-surface-700/60" />
      <span className="text-[10px] font-semibold text-gray-500 bg-surface-950 px-2.5 py-0.5 rounded-full border border-surface-700">
        {date}
      </span>
      <div className="flex-1 h-px bg-surface-700/60" />
    </div>
  )
}

function TypingIndicator({ identity, elapsedMs }: { identity: AgentIdentity; elapsedMs: number }) {
  const { t } = useTranslation()
  const isFresh = elapsedMs <= FRESH_ACTIVITY_MS
  const statusLabel = isFresh
    ? t('glassroom.agentActivelyThinking')
    : t('glassroom.agentStillWorking')

  return (
    <div className="flex items-center gap-2.5 px-4 py-2 animate-fade-in">
      <AgentAvatar identity={identity} size="sm" />
      <span className={`text-xs font-medium ${identity.color}`}>{identity.label}</span>
      {isFresh ? (
        <span className="flex gap-0.5 items-center">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-gray-500"
              style={{ animation: `typingBounce 1.2s ease-in-out ${i * 0.15}s infinite` }}
            />
          ))}
        </span>
      ) : (
        <Loader2 size={12} className="text-gray-500 animate-spin" />
      )}
      <span className="text-[11px] text-gray-600 italic">
        {statusLabel} · {formatElapsed(elapsedMs)}
      </span>
    </div>
  )
}

/** NeedsSplit inline banner — shown in the feed when that event arrives. */
function NeedsSplitBanner({ message }: { message: AgentMessage }) {
  const { t } = useTranslation()
  return (
    <div className="mx-4 my-2 flex items-start gap-3 p-3 rounded-lg border border-amber-500/30 bg-amber-950/20 animate-fade-in">
      <SplitSquareVertical size={15} className="text-amber-400 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-amber-300">{t('glassroom.scopeExceeded', { defaultValue: 'Sprint scope exceeded' })}</p>
        <p className="text-[11px] text-amber-200/60 mt-0.5 break-words">{message.content}</p>
        <p className="text-[10px] text-amber-200/40 mt-0.5">{formatTime(message.timestamp)}</p>
      </div>
    </div>
  )
}

// ── Message row / group ───────────────────────────────────────────────────────

function MessageRow({ msg }: { msg: AgentMessage }) {
  const isError = msg.type === 'error'
  return (
    <div className="group/msg flex items-start gap-2 relative hover:bg-surface-800/30 rounded px-1 -mx-1 py-0.5 transition-colors">
      <span className="opacity-0 group-hover/msg:opacity-100 text-[10px] text-gray-600 min-w-[3rem] text-right pt-0.5 transition-opacity select-none shrink-0">
        {formatTime(msg.timestamp)}
      </span>
      <div className="flex-1 min-w-0">
        <MessageContent text={msg.content} isError={isError} />
        <AssistantBadge msg={msg} />
        {msg.assistantDetail && (
          <p className="mt-1 text-[11px] text-gray-500 whitespace-pre-wrap break-words">
            {msg.assistantDetail}
          </p>
        )}
        {msg.preview && <PreviewCard preview={msg.preview} task={msg.task} />}
      </div>
      <CopyBtn text={msg.content} />
    </div>
  )
}

function SlackMessageGroup({ group, sprintId }: { group: MessageGroup; sprintId: string }) {
  const { identity, messages } = group
  const firstMsg = messages[0]
  const isError  = firstMsg?.type === 'error'

  return (
    <div className={`flex gap-3 px-4 py-1.5 animate-fade-in transition-colors ${
      isError ? 'bg-red-950/20 border-l-2 border-l-red-800/50' : 'hover:bg-surface-800/20'
    }`}>
      <div className="pt-0.5 shrink-0">
        <AgentAvatar identity={identity} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
          <span className={`font-bold text-[13px] ${identity.color}`}>{identity.label}</span>
          <TypeBadge type={firstMsg.type} />
          {firstMsg.task && firstMsg.taskId !== undefined && sprintId ? (
            <Link
              to={taskPath(sprintId, firstMsg.taskId)}
              className="text-[11px] text-gray-400 truncate max-w-[180px] hover:text-brand-300 hover:underline"
              title={firstMsg.task}
            >
              {firstMsg.task}
            </Link>
          ) : firstMsg.task && (
            <span className="text-[11px] text-gray-500 truncate max-w-[180px]" title={firstMsg.task}>
              {firstMsg.task}
            </span>
          )}
          <span className="text-[11px] text-gray-600 ml-auto shrink-0">
            {formatTime(firstMsg.timestamp)}
          </span>
        </div>
        {messages.map(msg => <MessageRow key={msg.id} msg={msg} />)}
      </div>
    </div>
  )
}

// ── Left sidebar: sprint selector + agent roster ──────────────────────────────

function LeftSidebar({
  sprintId, scope, status, activeAgents, onlineAgents,
}: {
  sprintId: string
  scope?: string
  status?: string
  activeAgents: { key: string; identity: AgentIdentity; elapsedMs: number }[]
  onlineAgents: AgentIdentity[]
}) {
  const { t } = useTranslation()
  const SCOPE_COLOR: Record<string, string> = {
    S: 'text-emerald-400',
    M: 'text-brand-400',
    L: 'text-amber-400',
  }

  const STATUS_DOT: Record<string, string> = {
    active:      'bg-emerald-400 animate-pulse',
    needs_split: 'bg-amber-400 animate-pulse',
    completed:   'bg-gray-400',
  }

  return (
    <div className="w-full border-r lg:border-r border-b lg:border-b-0 border-surface-700/60 bg-surface-950 flex flex-col lg:min-h-0 lg:w-auto lg:min-w-0">
      {/* Sprint info */}
      <div className="p-3 border-b border-surface-700/60">
        <div className="flex items-center gap-2 mb-1">
          <Hash size={12} className="text-gray-500" />
          <span className="text-xs font-semibold text-gray-300 truncate">{t('glassroom.sprintLabel', { id: sprintId, defaultValue: 'Sprint #{{id}}' })}</span>
        </div>
        <div className="flex items-center gap-2">
          {scope && (
            <span className={`flex items-center gap-1 text-[10px] font-semibold ${SCOPE_COLOR[scope] ?? 'text-gray-400'}`}>
              <Layers size={9} /> {scope}
            </span>
          )}
          {status && (
            <span className="flex items-center gap-1 text-[10px] text-gray-500">
              <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[status] ?? 'bg-gray-600'}`} />
              {status}
            </span>
          )}
        </div>
      </div>

      {/* Active agents */}
      <div className="py-2 xl:pb-24 xl:flex-1 xl:min-h-0 xl:overflow-y-auto">
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider px-3 mb-1">
          {t('glassroom.agentsTitle', 'Agents')}
        </p>
        {onlineAgents.length === 0 ? (
          <p className="text-[11px] text-gray-600 px-3 py-2 italic">{t('glassroom.waitingAgents', 'Waiting for agents…')}</p>
        ) : (
          onlineAgents.map((identity, i) => {
            const isActive = activeAgents.some(a => a.identity.initials === identity.initials)
            return (
              <div
                key={`${identity.label}-${i}`}
                className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-800/40 transition-colors rounded"
              >
                <AgentAvatar identity={identity} size="sm" />
                <span className={`text-[11px] font-medium ${identity.color} flex-1 truncate`}>
                  {identity.label}
                </span>
                {isActive
                  ? <Loader2 size={10} className="text-emerald-400 animate-spin shrink-0" />
                  : <span className="w-1.5 h-1.5 rounded-full bg-surface-700 shrink-0" />
                }
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ── Sprint Retrospective Panel ────────────────────────────────────────────────

function SprintRetroPanel({ retro }: { retro: SprintRetro | null }) {
  const { t } = useTranslation()
  if (!retro) return null

  const rate = retro.completionRate
  const rateTone = rate >= 80 ? 'text-emerald-400' : rate >= 50 ? 'text-amber-400' : 'text-red-400'
  const barColor = rate >= 80 ? 'bg-emerald-500' : rate >= 50 ? 'bg-amber-500' : 'bg-red-500'

  return (
    <div className="border-b border-surface-700/60 px-3 py-2.5">
      <div className="flex items-center gap-2 mb-2">
        <HeartPulse size={11} className="text-fuchsia-400" />
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
          {t('glassroom.retroTitle', 'Last Sprint Retro')}
        </p>
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-gray-400">{t('glassroom.retroCompletion', 'Completion')}</span>
          <span className={`text-[11px] font-semibold ${rateTone}`}>{rate}%</span>
        </div>
        <div className="w-full bg-surface-800 rounded-full h-1">
          <div className={`${barColor} h-1 rounded-full transition-all`} style={{ width: `${rate}%` }} />
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-1">
          <span className="text-[10px] text-gray-500">{t('glassroom.retroDone', 'Done')}</span>
          <span className="text-[10px] text-gray-300 text-right">{retro.doneTasks}/{retro.totalTasks}</span>
          <span className="text-[10px] text-gray-500">{t('glassroom.retroBlocked', 'Blocked')}</span>
          <span className={`text-[10px] text-right ${retro.blockedTasks > 0 ? 'text-amber-400' : 'text-gray-300'}`}>{retro.blockedTasks}</span>
          <span className="text-[10px] text-gray-500">{t('glassroom.retroRework', 'Rework cycles')}</span>
          <span className={`text-[10px] text-right ${retro.reworkCycles > 3 ? 'text-amber-400' : 'text-gray-300'}`}>{retro.reworkCycles}</span>
          <span className="text-[10px] text-gray-500">{t('glassroom.retroQA', 'QA failures')}</span>
          <span className={`text-[10px] text-right ${retro.qaFailures > 2 ? 'text-red-400' : 'text-gray-300'}`}>{retro.qaFailures}</span>
        </div>
      </div>
    </div>
  )
}

// ── Right panel: agent detail ─────────────────────────────────────────────────

function RightPanel({ sprintId, agentStates, messageCount, isConnected, assistantSummary, sprintTasks, healthEntries, autonomyTree, quotaTelemetry, lastRetro }: {
  sprintId: string
  agentStates: Record<string, { role: string; fsmState: string; currentActivity: string; color: string; lastSeen: string; lastTaskTitle?: string; lastTaskId?: number; lastSemanticType?: string }>
  messageCount: number
  isConnected: boolean
  assistantSummary: AssistantSummaryEntry[]
  sprintTasks: SprintTaskEntry[]
  healthEntries: HealthPanelEntry[]
  autonomyTree: TaskAutonomyEntry[]
  quotaTelemetry?: QuotaTelemetry
  lastRetro?: SprintRetro | null
}) {
  const { t } = useTranslation()
  const entries = Object.entries(agentStates)

  return (
    <div className="w-full border-l lg:border-l border-t lg:border-t-0 border-surface-700/60 bg-surface-950 flex flex-col lg:min-h-0 lg:w-auto lg:min-w-0 max-h-none lg:max-h-none overflow-visible lg:overflow-y-auto lg:overflow-x-hidden xl:pb-24">
      <div className="p-3 border-b border-surface-700/60">
        <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider">{t('glassroom.liveStateTitle')}</p>
      </div>

      <HealthPanel entries={healthEntries} />
      <SprintRetroPanel retro={lastRetro ?? null} />
      <QuotaTelemetryPanel quota={quotaTelemetry} />
      <SprintTaskPanel tasks={sprintTasks} sprintId={sprintId} />
      <TaskAutonomyTree tasks={autonomyTree} />
      <AssistantSummaryPanel entries={assistantSummary} />

      <div className="py-2 space-y-px shrink-0">
        {entries.length === 0 ? (
          <p className="text-[11px] text-gray-600 px-3 py-2 italic">{t('glassroom.noAgentActivity')}</p>
        ) : (
          entries.map(([role, state]) => {
            const identity = getAgent(role)
            return (
              <div key={role} className="px-3 py-2 hover:bg-surface-800/40 transition-colors">
                <div className="flex items-center gap-2 mb-1">
                  <AgentAvatar identity={identity} size="sm" />
                  <span className={`text-[11px] font-semibold ${identity.color} truncate flex-1`}>
                    {identity.label}
                  </span>
                </div>
                <div className="ml-7">
                  <span className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
                    state.fsmState === 'active'  ? 'bg-emerald-500/10 text-emerald-400' :
                    state.fsmState === 'waiting' ? 'bg-brand-500/10 text-brand-400'    :
                    state.fsmState === 'error'   ? 'bg-red-500/10 text-red-400'        :
                                                   'bg-surface-800 text-gray-600'
                  }`}>
                    {state.fsmState}
                  </span>
                  {state.currentActivity && (
                    <p className="text-[10px] text-gray-600 mt-0.5 break-words leading-tight line-clamp-2">
                      {state.currentActivity}
                    </p>
                  )}
                  {state.lastTaskTitle && (
                    <p className="text-[10px] text-gray-500 mt-1 break-words leading-tight">
                      {state.lastTaskTitle}
                    </p>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Stats footer */}
      <div className="p-3 border-t border-surface-700/60 space-y-1.5">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-gray-600">{t('glassroom.healthLabels.stream')}</span>
          <span className={`flex items-center gap-1 font-medium ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            {isConnected ? t('glassroom.streamStatus.live', 'Live') : t('glassroom.streamStatus.off', 'Off')}
          </span>
        </div>
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-gray-600">{t('glassroom.eventsLabel', 'Events')}</span>
          <span className="text-gray-400 font-medium tabular-nums">{messageCount}</span>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function GlassRoom({ sprintId: propSprintId }: { sprintId: string }) {
  const { t } = useTranslation()
  const eventTypes = useMemo(() => getEventTypes(t), [t])

  const { messages, agentStates, isConnected, connectionError, connect, disconnect, memoryHits, lastRetro } = useAgentStore()
  const activeSprintId = useAppStore(s => s.activeSprintId)
  const companyId = useAppStore(s => s.companyId)

  const numericId   = propSprintId ? parseInt(propSprintId, 10) : (activeSprintId ?? null)
  const { data: board } = useSprintBoard(isNaN(numericId as number) ? null : numericId)
  const { data: quotas } = useQuotas(companyId)
  const sprint = board?.sprint

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const containerRef   = useRef<HTMLDivElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [filterAgent, setFilterAgent]   = useState('')
  const [filterType,  setFilterType]    = useState('')
  const [searchText,  setSearchText]    = useState('')
  const [clockTick, setClockTick] = useState(() => Date.now())

  useEffect(() => {
    if (propSprintId) connect(propSprintId)
    return () => { disconnect() }
  }, [propSprintId])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    setIsAtBottom(el.scrollHeight - el.scrollTop <= el.clientHeight + 50)
  }, [])

  useEffect(() => {
    if (isAtBottom) {
      requestAnimationFrame(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
      })
    }
  }, [messages, isAtBottom])

  useEffect(() => {
    const timer = window.setInterval(() => setClockTick(Date.now()), 5000)
    return () => window.clearInterval(timer)
  }, [])

  const filteredMessages = useMemo(() => {
    let result = messages
    if (filterAgent) {
      result = result.filter(m => {
        const key = m.agent || m.role || ''
        return key.toLowerCase() === filterAgent.toLowerCase() ||
               getAgent(key).label.toLowerCase() === filterAgent.toLowerCase()
      })
    }
    if (filterType) result = result.filter(m => m.type === filterType)
    if (searchText) {
      const term = searchText.toLowerCase()
      result = result.filter(m => m.content.toLowerCase().includes(term))
    }
    return result
  }, [messages, filterAgent, filterType, searchText])

  const grouped = useMemo(() => groupMessages(filteredMessages), [filteredMessages])

  const activeAgents = useMemo(() => {
    const working = new Map<string, { identity: AgentIdentity; startedAt: number }>()
    const now = clockTick
    for (const msg of messages) {
      const key = msg.agent || msg.role || 'System'
      if (!key || key === 'System') continue
      if (msg.type === 'agent_start') {
        working.set(key, { identity: getAgent(key), startedAt: Date.parse(msg.timestamp || '') || now })
      } else if (msg.type === 'agent_complete' || msg.type === 'error' || msg.type === 'status') {
        working.delete(key)
      }
    }
    return [...working.entries()]
      .filter(([, v]) => now - v.startedAt <= ACTIVE_AGENT_TTL_MS)
      .map(([key, v]) => ({ key, identity: v.identity, elapsedMs: now - v.startedAt }))
  }, [messages, clockTick])

  const onlineAgents = useMemo(() => {
    const seen = new Map<string, AgentIdentity>()
    for (const msg of messages) {
      if (msg.agent && msg.agent !== 'System') seen.set(msg.agent, getAgent(msg.agent))
    }
    return [...seen.values()]
  }, [messages])

  const assistantSummary = useMemo<AssistantSummaryEntry[]>(() => {
    const summary = new Map<string, AssistantSummaryEntry>()
    for (const msg of messages) {
      if (!msg.assistantLabel || !msg.assistantDecision) continue
      const current = summary.get(msg.assistantLabel) ?? {
        label: msg.assistantLabel,
        used: 0,
        quotaSkips: 0,
        failures: 0,
        unavailableSkips: 0,
        requested: 0,
        cooldownUntil: undefined,
        lastDecision: undefined,
      }

      if (msg.assistantDecision === 'used') {
        current.used += 1
      } else if (msg.assistantDecision === 'quota_cooldown' || msg.assistantDecision === 'skipped_quota_cooldown') {
        current.quotaSkips += 1
      } else if (msg.assistantDecision === 'failed' || msg.assistantDecision === 'unavailable') {
        current.failures += 1
      } else if (msg.assistantDecision === 'requested') {
        current.requested += 1
      } else if (msg.assistantDecision === 'unavailable_cooldown' || msg.assistantDecision === 'skipped_unavailable_cooldown') {
        current.unavailableSkips += 1
      }

      current.lastDecision = msg.assistantDecision
      current.cooldownUntil = parseCooldownUntil(msg.assistantDetail) || current.cooldownUntil

      summary.set(msg.assistantLabel, current)
    }

    return [...summary.values()].sort((left, right) => left.label.localeCompare(right.label))
  }, [messages])

  const sprintTasks = useMemo<SprintTaskEntry[]>(() => {
    if (!board?.columns) return []

    const order: Array<BacklogItem['status']> = ['in_progress', 'in_review', 'blocked', 'todo', 'done']
    const entries = Object.values(board.columns)
      .flat()
      .map((task) => ({
        id: task.id,
        title: task.title,
        status: task.status,
        priority: task.priority,
        assignee: task.assignee,
        comments: task.comments,
      }))

    return entries.sort((left, right) => {
      const statusDelta = order.indexOf(left.status) - order.indexOf(right.status)
      if (statusDelta !== 0) return statusDelta
      return left.id - right.id
    })
  }, [board])

  const isFiltered = filterAgent || filterType || searchText

  const quotaTelemetry = useMemo<QuotaTelemetry | undefined>(() => {
    const rows = Array.isArray(quotas) ? quotas : []
    const quota = rows.reduce((total, row) => total + Number(row?.limit ?? row?.quota ?? 0), 0)
    const used = rows.reduce((total, row) => total + Number(row?.used ?? row?.token_used ?? 0), 0)
    if (!Number.isFinite(quota) || quota <= 0 || !Number.isFinite(used)) return undefined
    return {
      quota,
      used,
      remaining: Math.max(0, quota - used),
      ratio: Math.max(0, Math.min(1, used / quota)),
    }
  }, [quotas])

  const healthEntries = useMemo<HealthPanelEntry[]>(() => {
    const now = clockTick
    const liveRoles = Object.values(agentStates)
    const activeCount = liveRoles.filter(entry => entry.fsmState === 'active').length
    const errorCount = liveRoles.filter(entry => entry.fsmState === 'error').length
    const staleMs = liveRoles.length > 0
      ? Math.min(...liveRoles.map(entry => Math.max(0, now - Date.parse(entry.lastSeen || ''))))
      : 0
    const blockedCount = sprintTasks.filter(task => task.status === 'blocked').length
    const reworkOpen = messages.filter(msg => msg.semanticType === 'task.rework_scheduled').length

    const retroRate = lastRetro?.completionRate ?? null
    const retroTone: HealthPanelEntry['tone'] = retroRate === null ? 'neutral' : retroRate >= 80 ? 'good' : retroRate >= 50 ? 'warn' : 'danger'

    return [
      { label: t('glassroom.healthLabels.stream'), value: isConnected ? t('glassroom.streamStatus.live', 'Live') : t('glassroom.streamStatus.offline', 'Offline'), tone: isConnected ? 'good' : 'danger' },
      { label: t('glassroom.healthLabels.activeAgents'), value: String(activeCount), tone: activeCount > 0 ? 'good' : 'warn' },
      { label: t('glassroom.healthLabels.agentErrors'), value: String(errorCount), tone: errorCount > 0 ? 'danger' : 'good' },
      { label: t('glassroom.healthLabels.blockedTasks'), value: String(blockedCount), tone: blockedCount > 0 ? 'warn' : 'good' },
      { label: t('glassroom.healthLabels.openReworks'), value: String(reworkOpen), tone: reworkOpen > 0 ? 'warn' : 'neutral' },
      { label: t('glassroom.healthLabels.freshestHeartbeat'), value: liveRoles.length > 0 ? t('glassroom.agoWithValue', '{{value}} ago').replace('{{value}}', formatAgeShort(staleMs)) : t('glassroom.notAvailable', 'n/a'), tone: staleMs <= 30000 ? 'good' : 'warn' },
      { label: t('glassroom.healthLabels.memoryHits', 'Memory hits'), value: String(memoryHits), tone: memoryHits > 0 ? 'good' : 'neutral' },
      ...(retroRate !== null ? [{ label: t('glassroom.healthLabels.lastSprintCompletion', 'Last sprint'), value: `${retroRate}%`, tone: retroTone }] : []),
    ]
  }, [agentStates, clockTick, isConnected, messages, sprintTasks, memoryHits, lastRetro, t])

  const autonomyTree = useMemo<TaskAutonomyEntry[]>(() => {
    return sprintTasks.map(task => {
      const relatedMessages = messages.filter(msg => msg.taskId === task.id || msg.task === task.title)
      const reworkCount = relatedMessages.reduce((count, msg) => Math.max(count, msg.reworkCount ?? 0), 0)
      const reviewCount = (task.comments || []).filter(comment => comment.author === 'QA').length
      const deliverableCount = (task.comments || []).filter(hasDeliverableComment).length
      const currentPhase = [...relatedMessages].reverse().find(msg => msg.taskPhase)?.taskPhase || 'unknown'
      const blockedReason = task.status === 'blocked' ? extractBlockedReason(task.comments) : undefined
      const assistantLabels = [...new Set(relatedMessages.map(msg => msg.assistantLabel).filter(Boolean) as string[])]

      const stepStates: TaskAutonomyEntry['stepStates'] = [
        {
          key: 'queued',
          label: t('glassroom.treeSteps.queued'),
          state: relatedMessages.some(msg => msg.semanticType === 'task.queued') ? 'done' : task.status === 'todo' ? 'active' : 'pending',
        },
        {
          key: 'execution',
          label: t('glassroom.treeSteps.execution'),
          state: task.status === 'in_progress' ? 'active' : deliverableCount > 0 || ['in_review', 'done', 'blocked'].includes(task.status) ? 'done' : 'pending',
          detail: currentPhase !== 'unknown' ? phaseLabel(t, currentPhase) : undefined,
        },
        {
          key: 'review',
          label: t('glassroom.treeSteps.review'),
          state: task.status === 'in_review' ? 'active' : reviewCount > 0 || task.status === 'done' ? 'done' : task.status === 'blocked' && deliverableCount > 0 ? 'blocked' : 'pending',
          detail: reviewCount > 0 ? t('glassroom.reviewsCount', '{{n}} reviews').replace('{{n}}', String(reviewCount)) : undefined,
        },
        {
          key: 'rework',
          label: t('glassroom.treeSteps.rework'),
          state: reworkCount > 0 ? (task.status === 'blocked' ? 'blocked' : task.status === 'todo' ? 'active' : 'done') : 'pending',
          detail: reworkCount > 0 ? t('glassroom.cyclesCount', '{{n}} cycle(s)').replace('{{n}}', String(reworkCount)) : undefined,
        },
        {
          key: 'done',
          label: t('glassroom.treeSteps.done'),
          state: task.status === 'done' ? 'done' : task.status === 'blocked' ? 'blocked' : 'pending',
          detail: blockedReason,
        },
      ]

      return {
        id: task.id,
        title: task.title,
        status: task.status,
        priority: task.priority,
        assignee: task.assignee,
        currentPhase,
        reworkCount,
        reviewCount,
        deliverableCount,
        blockedReason,
        assistantLabels,
        stepStates,
      }
    }).sort((left, right) => {
      if (left.status === right.status) return left.id - right.id
      const order = ['in_progress', 'in_review', 'blocked', 'todo', 'done']
      return order.indexOf(left.status) - order.indexOf(right.status)
    })
  }, [messages, sprintTasks, t])

  return (
    <div className="flex flex-col min-h-full xl:h-full bg-surface-900">
      {/* Typing animation */}
      <style>{`
        @keyframes typingBounce {
          0%, 60%, 100% { transform: translateY(0) }
          30% { transform: translateY(-4px) }
        }
      `}</style>

      {/* ── Top bar ───────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 py-2 min-h-11 border-b border-surface-700/60 bg-surface-900 shrink-0 flex-wrap overflow-x-auto">
        <Hash size={13} className="text-gray-600" />
        <span className="text-sm font-semibold text-gray-200">{t('glassroom.sprintLabel', { id: propSprintId, defaultValue: 'Sprint #{{id}}' })}</span>
        {sprint?.scope_size && (
          <span className={`text-[10px] font-semibold flex items-center gap-0.5 ${
            sprint.scope_size === 'S' ? 'text-emerald-400' :
            sprint.scope_size === 'L' ? 'text-amber-400' : 'text-brand-400'
          }`}>
            <Layers size={9} />
            {sprint.scope_size}
          </span>
        )}
        <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />

        {/* Filters */}
        <div className="flex items-center gap-1.5 ml-3">
          <div className="relative">
            <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-600" />
            <input
              type="text"
              placeholder={t('glassroom.searchPlaceholder', { defaultValue: 'Search…' })}
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              className="pl-6 pr-5 py-1 text-[11px] bg-surface-800 border border-surface-700 rounded-md text-gray-300 placeholder-gray-600 focus:outline-none focus:border-brand-500 w-32 transition-colors"
            />
            {searchText && (
              <button onClick={() => setSearchText('')} className="absolute right-1.5 top-1/2 -translate-y-1/2">
                <X size={11} className="text-gray-500 hover:text-gray-300" />
              </button>
            )}
          </div>

          <select
            value={filterAgent}
            onChange={e => setFilterAgent(e.target.value)}
            className="py-1 px-2 text-[11px] bg-surface-800 border border-surface-700 rounded-md text-gray-300 focus:outline-none focus:border-brand-500"
          >
            <option value="">{t('glassroom.allAgents', 'All agents')}</option>
            {onlineAgents.map(a => (
              <option key={a.label} value={a.label}>{a.label}</option>
            ))}
          </select>

          <select
            value={filterType}
            onChange={e => setFilterType(e.target.value)}
            className="py-1 px-2 text-[11px] bg-surface-800 border border-surface-700 rounded-md text-gray-300 focus:outline-none focus:border-brand-500"
          >
            {eventTypes.map(et => (
              <option key={et.value} value={et.value}>{et.label}</option>
            ))}
          </select>

          {isFiltered && (
            <button
              onClick={() => { setFilterAgent(''); setFilterType(''); setSearchText('') }}
              className="p-1 hover:bg-surface-700 rounded text-gray-500 hover:text-gray-300 transition-colors"
              title={t('glassroom.clearFilters', { defaultValue: 'Clear filters' })}
            >
              <RotateCcw size={11} />
            </button>
          )}
        </div>

        {/* Presence avatars */}
        {onlineAgents.length > 0 && (
          <div className="flex items-center gap-1.5 ml-auto">
            <div className="flex -space-x-1.5">
              {onlineAgents.slice(0, 5).map((a, i) => (
                <div
                  key={`${a.label}-${i}`}
                  title={a.label}
                  className={`w-5 h-5 ${a.bg} rounded-md flex items-center justify-center text-[8px] font-bold text-white ring-1 ring-surface-900`}
                >
                  {a.initials}
                </div>
              ))}
              {onlineAgents.length > 5 && (
                <div className="w-5 h-5 bg-surface-700 rounded-md flex items-center justify-center text-[8px] font-bold text-gray-400 ring-1 ring-surface-900">
                  +{onlineAgents.length - 5}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Connection error ─────────────────────��─────────────────── */}
      {connectionError && (
        <div className="mx-3 mt-2 p-2 bg-red-950/30 border border-red-800/40 rounded-lg shrink-0 flex items-center gap-2">
          <ZapOff size={12} className="text-red-400 shrink-0" />
          <p className="text-red-400 text-[11px] flex-1">{connectionError}</p>
          {propSprintId && (
            <button
              onClick={() => connect(propSprintId)}
              className="text-[11px] text-red-300 hover:text-white font-medium shrink-0 underline underline-offset-2"
            >
              {t('glassroom.retryConnection')}
            </button>
          )}
        </div>
      )}

      {/* ── Body: sidebar + feed + panel ──────────────────────────── */}
      <div className="flex flex-1 min-h-0 flex-col overflow-visible lg:grid lg:grid-cols-[15rem_minmax(0,1fr)_22rem] 2xl:grid-cols-[17rem_minmax(0,1.2fr)_24rem] lg:overflow-hidden">
        {/* Left sidebar */}
        <LeftSidebar
          sprintId={propSprintId}
          scope={sprint?.scope_size}
          status={sprint?.status}
          activeAgents={activeAgents}
          onlineAgents={onlineAgents}
        />

        {/* Message feed */}
        <div className="relative flex-1 flex flex-col min-w-0 overflow-visible lg:overflow-hidden">
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="min-h-[20rem] py-2 xl:pb-24 overflow-visible lg:flex-1 lg:overflow-x-hidden lg:overflow-y-auto"
          >
            {messages.length === 0 ? (
              !isConnected && !connectionError ? (
                /* Connecting skeleton */
                <div className="flex flex-col gap-4 p-4 animate-pulse">
                  {[80, 60, 95, 45, 70].map((w, i) => (
                    <div key={i} className="flex gap-3 items-start">
                      <div className="w-7 h-7 rounded-lg bg-surface-700 shrink-0" />
                      <div className="flex-1 space-y-2">
                        <div className="h-2.5 bg-surface-700 rounded-full" style={{ width: `${w}%` }} />
                        <div className="h-2 bg-surface-800 rounded-full" style={{ width: `${w * 0.6}%` }} />
                      </div>
                    </div>
                  ))}
                  <p className="text-center text-xs text-gray-600 pt-2">{t('glassroom.connecting')}</p>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-center px-6">
                  <div className="w-14 h-14 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center mb-3">
                    <Bot size={24} className="text-brand-400 opacity-40" />
                  </div>
                  <p className="text-sm font-semibold text-gray-400">{t('glassroom.waiting')}</p>
                  <p className="text-xs text-gray-600 mt-1 max-w-[220px]">{t('glassroom.emptyState')}</p>
                </div>
              )
            ) : (
              grouped.map((day, di) => (
                <div key={di}>
                  <DateSeparator date={day.date} />
                  {day.groups.map((g, gi) => {
                    if (g.messages[0]?.type === ('needs_split' as any)) {
                      return <NeedsSplitBanner key={`${di}-${gi}`} message={g.messages[0]} />
                    }
                    return <SlackMessageGroup key={`${di}-${gi}`} group={g} sprintId={propSprintId} />
                  })}
                </div>
              ))
            )}

            {activeAgents.map(a => <TypingIndicator key={a.key} identity={a.identity} elapsedMs={a.elapsedMs} />)}
            <div ref={messagesEndRef} />
          </div>

          {/* Scroll-to-bottom prompt */}
          {!isAtBottom && messages.length > 0 && (
            <div className="absolute bottom-14 left-1/2 -translate-x-1/2">
              <button
                onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
                className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-brand-600/90 text-white text-[11px] font-medium shadow-lg hover:bg-brand-500 transition-colors"
              >
                <ChevronDown size={11} /> {t('glassroom.newMessages', { defaultValue: 'New messages' })}
              </button>
            </div>
          )}

          {/* Status bar */}
          <div className="px-4 py-1.5 border-t border-surface-700/60 shrink-0 flex items-center gap-3 bg-surface-900">
            <span className={`flex items-center gap-1.5 text-[10px] font-medium ${isConnected ? 'text-emerald-400' : 'text-gray-600'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-surface-600'}`} />
              {isConnected ? t('glassroom.connected') : t('glassroom.disconnected')}
            </span>
            <span className="text-[10px] text-gray-700">·</span>
            <span className="text-[10px] text-gray-600 tabular-nums">
              {isFiltered ? `${filteredMessages.length} / ${messages.length}` : messages.length} {t('glassroom.eventsLabel', 'Events').toLowerCase()}
            </span>
            {activeAgents.length > 0 && (
              <>
                <span className="text-[10px] text-gray-700">·</span>
                <span className="text-[10px] text-emerald-400 flex items-center gap-1">
                  <Loader2 size={9} className="animate-spin" />
                  {t('glassroom.agentsWorkingCount', { count: activeAgents.length, defaultValue: '{{count}} working' })}
                </span>
              </>
            )}
            {sprint?.status === 'needs_split' && (
              <>
                <span className="text-[10px] text-gray-700">·</span>
                <span className="flex items-center gap-1 text-[10px] text-amber-400 font-medium">
                  <SplitSquareVertical size={9} />
                  {t('glassroom.needsSplit')}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right panel */}
        <RightPanel
          sprintId={propSprintId}
          agentStates={agentStates}
          messageCount={messages.length}
          isConnected={isConnected}
          assistantSummary={assistantSummary}
          sprintTasks={sprintTasks}
          healthEntries={healthEntries}
          autonomyTree={autonomyTree}
          quotaTelemetry={quotaTelemetry}
          lastRetro={lastRetro}
        />
      </div>
    </div>
  )
}
