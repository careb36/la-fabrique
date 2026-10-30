import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

function ErrorFallback({ error, onReset }: { error: Error | null; onReset: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center min-h-[200px] gap-4 p-8 text-center">
      <div className="w-12 h-12 rounded-xl bg-red-900/30 border border-red-800/50 flex items-center justify-center">
        <AlertTriangle size={24} className="text-red-400" />
      </div>
      <div>
        <p className="font-semibold text-gray-200 mb-1">{t('errorBoundary.title')}</p>
        <p className="text-xs text-gray-500 max-w-xs">
          {error?.message ?? t('errorBoundary.description')}
        </p>
      </div>
      <button onClick={onReset} className="btn btn-secondary btn-sm flex items-center gap-1.5">
        <RefreshCw size={13} />
        {t('errorBoundary.retry')}
      </button>
    </div>
  )
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  reset = () => this.setState({ hasError: false, error: null })

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return <ErrorFallback error={this.state.error} onReset={this.reset} />
    }
    return this.props.children
  }
}
