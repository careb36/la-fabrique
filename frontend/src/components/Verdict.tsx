import { useTranslation } from 'react-i18next'
import { AlertCircle, CheckCircle2, Clock3, HelpCircle } from 'lucide-react'
import type { AgentRunStatus } from '../services/api'

export const VERDICT_PRESENTATION: Record<AgentRunStatus, { className: string; Icon: typeof CheckCircle2 }> = {
  verified: { className: 'text-emerald-300 bg-emerald-950/60 border-emerald-700/50', Icon: CheckCircle2 },
  refuted: { className: 'text-red-300 bg-red-950/60 border-red-700/50', Icon: AlertCircle },
  unverifiable: { className: 'text-violet-300 bg-violet-950/60 border-violet-700/50', Icon: HelpCircle },
  ingested: { className: 'text-amber-300 bg-amber-950/60 border-amber-700/50', Icon: Clock3 },
}

/** The verdict badge used by every evidence surface (list, detail, task, board). */
export function Verdict({ status, compact = false }: { status: AgentRunStatus; compact?: boolean }) {
  const { t } = useTranslation()
  const { className, Icon } = VERDICT_PRESENTATION[status]
  const size = compact ? 'gap-1 px-1.5 py-0.5 text-[11px]' : 'gap-1.5 px-2.5 py-1 text-xs'
  return (
    <span
      data-testid={`verdict-${status}`}
      className={`inline-flex items-center rounded-full border font-semibold ${size} ${className}`}
    >
      <Icon data-testid={`verdict-icon-${status}`} size={compact ? 11 : 14} aria-hidden="true" />
      {t(`evidence.verdict.${status}`)}
    </span>
  )
}
