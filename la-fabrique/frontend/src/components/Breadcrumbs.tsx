import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronRight } from 'lucide-react'

export interface Crumb {
  label: string
  to?: string
}

/**
 * Trail from a section to the current page. The last crumb is plain text and
 * deliberately carries no `aria-current`: the primary navigation owns the single
 * `aria-current="page"` marker on every route.
 */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  const { t } = useTranslation()
  return (
    <nav aria-label={t('nav.breadcrumb', { defaultValue: 'Breadcrumb' })} className="min-w-0 text-sm">
      <ol className="flex min-w-0 flex-wrap items-center gap-1.5 text-gray-400">
        {items.map((item, index) => (
          <li key={`${index}-${item.label}`} className="flex min-w-0 items-center gap-1.5">
            {index > 0 && <ChevronRight size={14} aria-hidden="true" className="shrink-0 text-gray-600" />}
            {item.to
              ? <Link to={item.to} className="truncate hover:text-white transition-colors">{item.label}</Link>
              : <span className="truncate text-gray-200">{item.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  )
}
