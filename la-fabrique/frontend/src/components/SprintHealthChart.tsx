/**
 * SprintHealthChart — visualizes sprint health metrics over time.
 *
 * Displays a simple bar chart showing task completion progress
 * and health score trends.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

interface SprintHealthChartProps {
  total: number
  done: number
  inProgress: number
  blocked: number
  healthScore: number | null
}

export function SprintHealthChart({
  total,
  done,
  inProgress,
  blocked,
  healthScore,
}: SprintHealthChartProps) {
  const { t } = useTranslation()

  const percentages = useMemo(() => {
    if (total === 0) return { done: 0, inProgress: 0, blocked: 0, remaining: 100 }
    return {
      done: Math.round((done / total) * 100),
      inProgress: Math.round((inProgress / total) * 100),
      blocked: Math.round((blocked / total) * 100),
      remaining: Math.round(((total - done - inProgress - blocked) / total) * 100),
    }
  }, [total, done, inProgress, blocked])

  const healthColor = useMemo(() => {
    if (healthScore === null) return 'text-gray-400'
    if (healthScore >= 80) return 'text-emerald-400'
    if (healthScore >= 60) return 'text-amber-400'
    return 'text-red-400'
  }, [healthScore])

  if (total === 0) {
    return (
      <div className="rounded-xl border border-surface-700 bg-surface-900 p-4">
        <p className="text-xs text-gray-500 text-center">{t('dashboard.noData', { defaultValue: 'No sprint data available' })}</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-surface-700 bg-surface-900 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">{t('dashboard.sprintHealth', { defaultValue: 'Sprint Health' })}</h3>
        {healthScore !== null && (
          <span className={`text-lg font-bold tabular-nums ${healthColor}`}>
            {healthScore}
          </span>
        )}
      </div>

      {/* Stacked progress bar */}
      <div className="space-y-2">
        <div className="flex h-3 rounded-full overflow-hidden bg-surface-700">
          {percentages.done > 0 && (
            <div
              className="bg-emerald-500 transition-all duration-500"
              style={{ width: `${percentages.done}%` }}
              title={t('dashboard.chartTooltip', {
                defaultValue: '{{label}}: {{percent}}%',
                label: t('dashboard.done', { defaultValue: 'Done' }),
                percent: percentages.done,
              })}
            />
          )}
          {percentages.inProgress > 0 && (
            <div
              className="bg-brand-500 transition-all duration-500"
              style={{ width: `${percentages.inProgress}%` }}
              title={t('dashboard.chartTooltip', {
                defaultValue: '{{label}}: {{percent}}%',
                label: t('dashboard.inProgress', { defaultValue: 'In Progress' }),
                percent: percentages.inProgress,
              })}
            />
          )}
          {percentages.blocked > 0 && (
            <div
              className="bg-red-500 transition-all duration-500"
              style={{ width: `${percentages.blocked}%` }}
              title={t('dashboard.chartTooltip', {
                defaultValue: '{{label}}: {{percent}}%',
                label: t('dashboard.blocked', { defaultValue: 'Blocked' }),
                percent: percentages.blocked,
              })}
            />
          )}
          {percentages.remaining > 0 && (
            <div
              className="bg-surface-600 transition-all duration-500"
              style={{ width: `${percentages.remaining}%` }}
              title={t('dashboard.chartTooltip', {
                defaultValue: '{{label}}: {{percent}}%',
                label: t('dashboard.remaining', { defaultValue: 'Remaining' }),
                percent: percentages.remaining,
              })}
            />
          )}
        </div>

        {/* Legend */}
        <div className="flex items-center justify-between text-[11px]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-gray-400">{t('dashboard.done', { defaultValue: 'Done' })} ({done})</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-brand-500" />
              <span className="text-gray-400">{t('dashboard.inProgress', { defaultValue: 'In Progress' })} ({inProgress})</span>
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="text-gray-400">{t('dashboard.blocked', { defaultValue: 'Blocked' })} ({blocked})</span>
            </span>
          </div>
          <span className="text-gray-500 tabular-nums">
            {done}/{total} {t('dashboard.tasks', { defaultValue: 'tasks' })}
          </span>
        </div>
      </div>

      {/* Health score indicator */}
      {healthScore !== null && (
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-gray-500">
            <span>{t('dashboard.healthScore', { defaultValue: 'Health Score' })}</span>
            <span className="tabular-nums">{healthScore}/100</span>
          </div>
          <div className="h-1.5 bg-surface-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                healthScore >= 80
                  ? 'bg-emerald-500'
                  : healthScore >= 60
                    ? 'bg-amber-500'
                    : 'bg-red-500'
              }`}
              style={{ width: `${healthScore}%` }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
