import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'

export default function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-6 p-8 text-center">
      <div className="w-16 h-16 rounded-2xl bg-surface-800 border border-surface-700 flex items-center justify-center">
        <Compass size={32} className="text-brand-400" />
      </div>
      <div>
        <h1 className="text-4xl font-black text-white mb-2">404</h1>
        <p className="text-lg font-semibold text-gray-200 mb-1">{t('notFound.title')}</p>
        <p className="text-sm text-gray-500 max-w-sm">{t('notFound.description')}</p>
      </div>
      <Link
        to="/dashboard"
        className="btn btn-primary flex items-center gap-2"
      >
        {t('notFound.backHome')}
      </Link>
    </div>
  )
}
