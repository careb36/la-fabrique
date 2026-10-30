import React from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useAnalyticsSummary, useOrchestrationHealth, useSprintBoard } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'
import { TrendingUp, Zap, CheckSquare, XSquare, Info, RefreshCw, Activity } from 'lucide-react'
import type { OrchestrationHealthWeek } from '../services/api'

function HealthBadge({ score }: { score: number }) {
  const { t } = useTranslation()
  const color = score >= 80 ? 'text-status-success' : score >= 50 ? 'text-yellow-400' : 'text-status-error'
  const bg    = score >= 80 ? 'bg-green-900/30 border-green-700/40' : score >= 50 ? 'bg-yellow-900/30 border-yellow-700/40' : 'bg-red-900/30 border-red-700/40'

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${bg} group relative`}>
      <span className={`text-2xl font-black ${color}`}>{score}</span>
      <div>
        <p className="text-xs text-gray-400 leading-none">{t('analytics.healthScore')}</p>
        <p className="text-xs text-gray-500">/100</p>
      </div>
      {/* Tooltip */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 bg-surface-800 border border-surface-700 rounded-lg p-3 text-xs text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 shadow-card-md">
        {t('analytics.healthExplainer', 'Composite score: task completion rate, blocked items, and sprint velocity')}
      </div>
    </div>
  )
}

// ── Inline SVG bar chart for weekly trend ────────────────────────────────────

function WeeklyTrendChart({ weeks }: { weeks: OrchestrationHealthWeek[] }) {
  const { t } = useTranslation()
  if (weeks.length === 0) return null

  const maxRate = Math.max(...weeks.map(w => w.qa_needs_work_rate), 0.001)
  const BAR_H = 48
  const BAR_W = 20
  const GAP = 6
  const totalW = weeks.length * (BAR_W + GAP) - GAP

  return (
    <div className="overflow-x-auto">
      <svg width={totalW} height={BAR_H + 24} aria-hidden="true">
        {weeks.map((w, i) => {
          const barHeight = Math.round((w.qa_needs_work_rate / maxRate) * BAR_H)
          const x = i * (BAR_W + GAP)
          const y = BAR_H - barHeight
          const fill = w.post_batch1 ? '#22d3ee' : '#818cf8' // cyan = post, indigo = pre
          return (
            <g key={w.week}>
              <title>{w.week}: {(w.qa_needs_work_rate * 100).toFixed(1)}%</title>
              <rect x={x} y={y} width={BAR_W} height={barHeight} fill={fill} rx={2} opacity={0.85} />
              {/* week label — only first and last to avoid clutter */}
              {(i === 0 || i === weeks.length - 1) && (
                <text x={x + BAR_W / 2} y={BAR_H + 16} textAnchor="middle" fontSize={8} fill="#9ca3af">
                  {w.week.slice(5)} {/* "W18" portion */}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-[#818cf8]" />
          {t('analytics.orchestration_health.pre_batch1')}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-[#22d3ee]" />
          {t('analytics.orchestration_health.post_batch1')}
        </span>
      </div>
    </div>
  )
}

// ── Orchestration Health section ──────────────────────────────────────────────

function OrchestrationHealthSection({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useOrchestrationHealth(companyId)

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <div key={i} className="skeleton h-24 rounded-lg" />)}
        </div>
        <div className="skeleton h-32 rounded-lg" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="alert-error flex items-center gap-2">
        <XSquare size={16} /> {t('analytics.error')}
      </div>
    )
  }

  if (!data) return null

  const { weeks, summary, anchor_date } = data
  const pre = summary.pre_batch1
  const post = summary.post_batch1
  // Turns without a reported count are left out of the average, and said so.
  const unreportedTurns = weeks.reduce((sum, w) => sum + (w.developer_turns_without_tokens ?? 0), 0)

  const kpis = [
    {
      label: t('analytics.orchestration_health.qa_rate'),
      pre: `${(pre.qa_needs_work_rate * 100).toFixed(1)}%`,
      post: `${(post.qa_needs_work_rate * 100).toFixed(1)}%`,
    },
    {
      label: t('analytics.orchestration_health.avg_tokens'),
      pre: Math.round(pre.avg_developer_tokens).toLocaleString(),
      post: Math.round(post.avg_developer_tokens).toLocaleString(),
      note: unreportedTurns > 0
        ? t('analytics.orchestration_health.tokens_unreported', { count: unreportedTurns })
        : undefined,
    },
    {
      label: t('analytics.orchestration_health.consult_freq'),
      pre: null,
      post: null,
      raw: weeks.length > 0
        ? weeks.filter(w => w.post_batch1).reduce((s, w) => s + w.architect_consult_count, 0)
        : '—',
    },
  ]

  return (
    <div className="space-y-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="text-cyan-400" size={18} />
          <h3 className="text-base font-bold text-white">{t('analytics.orchestration_health.title')}</h3>
          {anchor_date && (
            <span className="text-xs text-gray-500">
              ({t('analytics.orchestration_health.anchor_date')}: {anchor_date})
            </span>
          )}
        </div>
        <button onClick={() => refetch()} className="btn-ghost btn-icon" title={t('common.refresh', 'Refresh')}>
          <RefreshCw size={13} />
        </button>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {kpis.map(kpi => (
          <div key={kpi.label} className="card p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3">{kpi.label}</p>
            {kpi.raw !== undefined ? (
              <p className="text-3xl font-black text-white">{kpi.raw}</p>
            ) : (
              <div className="flex gap-4">
                <div>
                  <p className="text-[10px] text-indigo-400 font-semibold mb-0.5">{t('analytics.orchestration_health.pre_batch1')}</p>
                  <p className="text-xl font-black text-white">{kpi.pre}</p>
                </div>
                <div>
                  <p className="text-[10px] text-cyan-400 font-semibold mb-0.5">{t('analytics.orchestration_health.post_batch1')}</p>
                  <p className="text-xl font-black text-white">{kpi.post}</p>
                </div>
              </div>
            )}
            {'note' in kpi && kpi.note && <p className="mt-2 text-xs text-amber-300">{kpi.note}</p>}
          </div>
        ))}
      </div>

      {/* Weekly trend chart or empty state */}
      {weeks.length === 0 ? (
        <div className="card p-6 text-center text-gray-500 text-sm">
          {t('analytics.orchestration_health.empty')}
        </div>
      ) : (
        <div className="card p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3 flex items-center gap-1.5">
            <Info size={12} />
            {t('analytics.orchestration_health.weekly_trend')} — {t('analytics.orchestration_health.qa_rate')}
          </p>
          <WeeklyTrendChart weeks={weeks} />
        </div>
      )}
    </div>
  )
}

export const AnalyticsDashboard: React.FC<{ sprintId: number }> = ({ sprintId }) => {
  const { t } = useTranslation()
  useSprintBoard(sprintId || null)
  const { data, isLoading, isError, refetch } = useAnalyticsSummary(sprintId)
  const companyId = useAppStore(state => state.companyId)

  if (!sprintId) {
    return (
      <div className="empty-state py-16">
        <p className="text-gray-400 mb-4">{t('workspace.noSprint')}</p>
        <Link to="/sprints" className="btn btn-ghost">{t('nav.sprints', { defaultValue: 'Sprints' })}</Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[1,2,3].map(i => <div key={i} className="skeleton h-24 rounded-lg" />)}
        </div>
        <div className="skeleton h-32 rounded-lg" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="alert-error flex items-center gap-2">
        <XSquare size={16} /> {t('analytics.error')}
        <button onClick={() => refetch()} className="btn btn-ghost btn-sm">{t('common.retry')}</button>
      </div>
    )
  }

  const analytics = data

  const done    = analytics.tasks_completed ?? 0
  const failed  = analytics.tasks_failed    ?? 0
  const inProg  = analytics.tasks_in_progress ?? 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="text-brand-400" size={22} />
          <div>
            <h2 className="text-xl font-bold text-white">{t('analytics.title')}</h2>
            <p className="text-gray-500 text-sm">{t('analytics.subtitle')}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <HealthBadge score={analytics.health_score} />
          <button onClick={() => refetch()} className="btn-ghost btn-icon" title={t('common.refresh','Refresh')}>
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card p-4">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={14} className="text-brand-400" />
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">{t('analytics.tokensConsumed')}</p>
          </div>
          <p className="text-3xl font-black text-white">{analytics.tokens_consumed.toLocaleString()}</p>
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2 mb-2">
            <CheckSquare size={14} className="text-status-success" />
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">{t('analytics.tasksCompleted')}</p>
          </div>
          <p className="text-3xl font-black text-white">{done}</p>
          {inProg > 0 && <p className="text-xs text-gray-500 mt-1">{inProg} {t('analytics.inProgress')}</p>}
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2 mb-2">
            <XSquare size={14} className="text-status-error" />
            <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold">{t('analytics.tasksFailed')}</p>
          </div>
          <p className="text-3xl font-black text-white">{failed}</p>
        </div>
      </div>

      {/* Tokens by agent */}
      {analytics.agent_breakdown && analytics.agent_breakdown.length > 0 && (
        <div className="card p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3 flex items-center gap-1.5">
            <Info size={12} />
            {t('analytics.tokensByAgent')}
          </p>
          <div className="space-y-2">
            {analytics.agent_breakdown.map(({ role, tokens, percentage }: { role: string; tokens: number; percentage: number }) => (
              <div key={role}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-400">{role}</span>
                  <span className="text-gray-500">{tokens.toLocaleString()} ({percentage}%)</span>
                </div>
                <div className="h-1.5 bg-surface-700 rounded-full overflow-hidden">
                  <div className="h-full bg-brand-500 rounded-full" style={{ width: `${percentage}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Executive summary */}
      {analytics.executive_summary && (
        <div className="card p-4 border-l-4 border-l-brand-500">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-2">{t('analytics.executiveSummary')}</p>
          <p className="text-gray-300 leading-relaxed italic">"{analytics.executive_summary}"</p>
        </div>
      )}

      {/* Orchestration Health */}
      {companyId && (
        <div className="pt-2 border-t border-surface-700">
          <OrchestrationHealthSection companyId={companyId} />
        </div>
      )}
    </div>
  )
}
