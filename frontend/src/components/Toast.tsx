import { CheckCircle2, AlertTriangle, Info, XCircle, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useToastStore, type Toast, type ToastVariant } from '../store/toastStore'

const VARIANT_STYLES: Record<ToastVariant, { bar: string; icon: string; bg: string; border: string }> = {
  success: { bar: 'bg-emerald-500', icon: 'text-emerald-400', bg: 'bg-surface-900', border: 'border-emerald-800/50' },
  error:   { bar: 'bg-red-500',     icon: 'text-red-400',     bg: 'bg-surface-900', border: 'border-red-800/50'     },
  warning: { bar: 'bg-amber-500',   icon: 'text-amber-400',   bg: 'bg-surface-900', border: 'border-amber-800/50'   },
  info:    { bar: 'bg-brand-500',   icon: 'text-brand-400',   bg: 'bg-surface-900', border: 'border-brand-800/50'   },
}

const VARIANT_ICONS: Record<ToastVariant, React.ElementType> = {
  success: CheckCircle2,
  error:   XCircle,
  warning: AlertTriangle,
  info:    Info,
}

function ToastItem({ toast }: { toast: Toast }) {
  const { t } = useTranslation()
  const dismiss = useToastStore(s => s.dismiss)
  const styles  = VARIANT_STYLES[toast.variant]
  const Icon    = VARIANT_ICONS[toast.variant]

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`
        relative flex items-start gap-3 w-80 rounded-xl border px-4 py-3 shadow-card-md
        animate-slide-in overflow-hidden ${styles.bg} ${styles.border}
      `}
    >
      {/* accent bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-1 ${styles.bar} rounded-l-xl`} />

      <Icon size={16} className={`${styles.icon} shrink-0 mt-0.5`} />

      <p className="flex-1 text-sm text-gray-200 leading-snug">{toast.message}</p>

      <button
        onClick={() => dismiss(toast.id)}
        className="shrink-0 text-gray-500 hover:text-gray-300 transition-colors"
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const toasts = useToastStore(s => s.toasts)
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 items-end">
      {toasts.map(t => <ToastItem key={t.id} toast={t} />)}
    </div>
  )
}
