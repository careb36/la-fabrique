import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { queryClient } from '../lib/queryClient'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'
import { safeReturnPath } from '../lib/returnPath'

export default function CompanySelect() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const memberships = useAuthStore(state => state.memberships)
  const setCompany = useAppStore(state => state.setCompany)

  function selectCompany(companyId: number) {
    queryClient.removeQueries()
    setCompany(
      companyId,
      t('auth.companyPlaceholder', { id: companyId, defaultValue: 'Company {{id}}' }),
    )
    navigate(safeReturnPath(searchParams.get('from')), { replace: true })
  }

  return (
    <div className="page-container max-w-2xl">
      <h1 className="text-2xl font-bold text-white mb-6">
        {t('auth.selectCompany', { defaultValue: 'Select a company' })}
      </h1>
      <ul className="space-y-3">
        {memberships.map(({ company_id, human_role }) => (
          <li key={company_id}>
            <button
              type="button"
              onClick={() => selectCompany(company_id)}
              className="w-full flex items-center justify-between rounded-lg border border-surface-700 bg-surface-800 px-4 py-3 text-left text-white hover:border-brand-500"
            >
              <span>{t('auth.companyPlaceholder', {
                id: company_id,
                defaultValue: 'Company {{id}}',
              })}</span>
              <span className="text-sm text-gray-400">{human_role}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
