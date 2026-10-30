/**
 * ErrorState — reusable error display component.
 */

import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'

interface ErrorStateProps {
  message: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({ message, onRetry, className = '' }: ErrorStateProps) {
  const { t } = useTranslation()
  return (
    <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
      <div className="p-3 rounded-full bg-red-500/10 mb-3">
        <AlertTriangle size={24} className="text-red-400" />
      </div>
      <p className="text-sm font-medium text-red-300 mb-1">{t('errorState.title', { defaultValue: 'Something went wrong' })}</p>
      <p className="text-xs text-gray-500 text-center max-w-xs mb-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-surface-700 text-xs font-medium text-gray-300 hover:text-white hover:border-surface-600 transition-colors"
        >
          <RefreshCw size={12} />
          {t('errorState.retry', { defaultValue: 'Try again' })}
        </button>
      )}
    </div>
  )
}
