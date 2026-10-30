import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, BarChart3, Download, Loader2, RotateCcw, ShieldCheck } from 'lucide-react'
import { useQuotas, useQuotaUsageHistory, useResetQuota } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'


// No limit configured for a business unit.
const UNLIMITED = '∞'

export const QuotaPanel: React.FC = () => {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const { data: quotaData } = useQuotas(companyId)
  const [days, setDays] = useState(7)
  const { data: historyData } = useQuotaUsageHistory(companyId, days)
  const resetQuotaMutation = useResetQuota()
  const [pendingResets, setPendingResets] = useState<Set<number>>(new Set())

  const quotas = Array.isArray(quotaData) ? quotaData : []
  const history = historyData?.days ?? []
  const maxTokens = Math.max(1, ...history.map((d: any) => d.tokens))

  const exportCsv = () => {
    const rows = [['date', 'tokens']]
    for (const d of history) rows.push([d.date, String(d.tokens)])
    const csv = rows.map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `quota_usage_${companyId}_${days}d.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck className="text-brand-400" size={22} />
          <h1 className="text-xl font-bold text-white">{t('governance.quotaTitle', { defaultValue: 'Token Quota Usage' })}</h1>
        </div>
        <button onClick={exportCsv} className="btn-ghost btn-sm flex items-center gap-1.5" title={t('governance.exportCsv', { defaultValue: 'Export CSV' })}>
          <Download size={14} /> CSV
        </button>
      </div>

      {/* Per-unit quotas */}
      {quotas.length > 0 && (
        <section className="mb-6">
          <div className="space-y-3">
            {quotas.map((unit: any) => {
              const pct = unit.limit > 0 ? Math.min(100, Math.round((unit.used / unit.limit) * 100)) : 0
              const isWarning = pct >= 80 && pct < 100
              const isExceeded = unit.limit > 0 && unit.used >= unit.limit
              const barColor = isExceeded ? 'bg-status-error' : isWarning ? 'bg-yellow-500' : 'bg-brand-500'
              return (
                <div key={unit.id ?? unit.unit} className="card p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-gray-300">{unit.unit}</span>
                    <div className="flex items-center gap-2">
                      {isExceeded && <span className="badge bg-red-900/60 text-red-300">{t('governance.quotaExceeded')}</span>}
                      {isWarning && !isExceeded && <span className="badge bg-yellow-900/60 text-yellow-300"><AlertTriangle size={10} />{t('governance.quotaWarning')}</span>}
                      <span className="text-xs text-gray-500">
                        {unit.used.toLocaleString()} / {unit.limit > 0 ? unit.limit.toLocaleString() : UNLIMITED} {t('governance.tokens')}
                      </span>
                      {unit.id && (
                        <button
                          onClick={() => {
                            setPendingResets(previous => new Set(previous).add(unit.id))
                            resetQuotaMutation.mutate(unit.id, {
                              onSettled: () => setPendingResets(previous => {
                                const next = new Set(previous)
                                next.delete(unit.id)
                                return next
                              }),
                            })
                          }}
                          disabled={pendingResets.has(unit.id)}
                          className="btn-ghost btn-sm p-1"
                          title={t('governance.resetQuota')}
                        >
                          {pendingResets.has(unit.id)
                            ? <Loader2 size={12} className="animate-spin" />
                            : <RotateCcw size={12} />}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="h-2 w-full rounded-full bg-surface-700">
                    <div className={`h-2 rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${unit.limit > 0 ? pct : 0}%` }} />
                  </div>
                  {unit.limit > 0 && <p className="mt-1 text-right text-xs text-gray-600">{pct}%</p>}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Historical usage chart */}
      {history.length > 0 && (
        <section className="mb-6">
          <div className="mb-2 flex items-center gap-2">
            <BarChart3 size={18} className="text-brand-400" />
            <h2 className="text-sm font-semibold text-gray-200">{t('governance.usageHistory', { defaultValue: 'Usage history' })}</h2>
            <select value={days} onChange={e => setDays(Number(e.target.value))} className="ml-auto text-xs bg-surface-800 border border-surface-700 rounded px-2 py-1 text-gray-300">
              <option value={7}>{t('governance.lastDays', { count: 7, defaultValue: '{{count}} days' })}</option>
              <option value={14}>{t('governance.lastDays', { count: 14, defaultValue: '{{count}} days' })}</option>
              <option value={30}>{t('governance.lastDays', { count: 30, defaultValue: '{{count}} days' })}</option>
            </select>
          </div>
          <div className="card p-3">
            <div className="flex items-end gap-1 h-32">
              {history.map((d: any) => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    className="w-full bg-brand-500/70 rounded-t transition-all"
                    style={{ height: `${Math.max(2, (d.tokens / maxTokens) * 100)}%` }}
                    title={`${d.date}: ${d.tokens.toLocaleString()} tokens`}
                  />
                  <span className="text-[9px] text-gray-500 rotate-[-45deg] origin-left whitespace-nowrap">{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-gray-500 text-right">{t('governance.totalTokens', { total: historyData?.total?.toLocaleString() ?? 0, defaultValue: 'Total: {{total}} tokens' })}</p>
          </div>
        </section>
      )}

      {companyId === null && <div className="empty-state py-12"><AlertTriangle size={32} className="mx-auto mb-3 text-gray-500" /><p className="text-gray-400">{t('evidence.selectCompany')}</p></div>}
    </div>
  )
}
