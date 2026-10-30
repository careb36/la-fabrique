import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, UserPlus, Users } from 'lucide-react'
import { useCurrentRole, useInviteMember } from '../hooks/useQueries'
import { ApiError, errorDetail, type CompanyRole } from '../services/api'
import { useAppStore } from '../store/useAppStore'

const ROLES: CompanyRole[] = ['Viewer', 'Manager', 'Owner']

/**
 * Company members: an Owner invites a user who already has an account
 * (`POST /v1/company/invite`). The API has no endpoint that lists members.
 */
export default function CompanyMembers() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const companyName = useAppStore(state => state.companyName)
  const role = useCurrentRole()
  const invite = useInviteMember()
  const [email, setEmail] = useState('')
  const [humanRole, setHumanRole] = useState<CompanyRole>('Viewer')
  const [invited, setInvited] = useState<{ email: string; role: CompanyRole } | null>(null)

  function submit() {
    const address = email.trim()
    if (!address || companyId === null) return
    setInvited(null)
    invite.mutate(
      { company_id: companyId, email: address, human_role: humanRole },
      { onSuccess: () => { setInvited({ email: address, role: humanRole }); setEmail('') } },
    )
  }

  const status = invite.error instanceof ApiError ? invite.error.status : null
  const errorMessage = status === 404
    ? t('members.noAccount', { defaultValue: 'There is no account with that email. Ask them to register first, then invite them.' })
    : status === 409
      ? t('members.alreadyMember', { defaultValue: 'They are already a member of this company. Roles cannot be changed from here yet.' })
      : t('members.inviteError', { message: errorDetail(invite.error), defaultValue: 'Could not invite: {{message}}' })

  return (
    <div className="page-container max-w-2xl">
      <div className="page-header mb-6">
        <div>
          <div className="flex items-center gap-2">
            <Users className="text-brand-400" size={22} />
            <h1 className="page-title">{t('members.title', { defaultValue: 'Members' })}</h1>
          </div>
          <p className="text-gray-400 mt-1">
            {t('members.subtitle', { company: companyName || companyId, defaultValue: 'People who can work in {{company}}.' })}
          </p>
        </div>
      </div>

      {role !== 'Owner' ? (
        <div role="status" className="card p-4 text-sm text-gray-300">
          {t('members.ownerOnly', { role: role ?? '—', defaultValue: 'Only owners can invite members. Your role here is {{role}}.' })}
        </div>
      ) : (
        <form onSubmit={e => { e.preventDefault(); submit() }} className="card p-4 space-y-4" aria-labelledby="invite-title">
          <h2 id="invite-title" className="text-sm font-semibold text-white">
            {t('members.inviteTitle', { defaultValue: 'Invite a member' })}
          </h2>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <label className="block">
              <span className="input-label">{t('members.email', { defaultValue: 'Email of their account' })}</span>
              <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
                placeholder={t('members.emailPlaceholder', { defaultValue: 'name@company.com' })}
                className="input w-full" />
            </label>
            <label className="block">
              <span className="input-label">{t('members.role', { defaultValue: 'Role' })}</span>
              <select value={humanRole} onChange={e => setHumanRole(e.target.value as CompanyRole)} className="select w-full">
                {ROLES.map(value => (
                  <option key={value} value={value}>{t(`members.roles.${value}`, { defaultValue: value })}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-xs text-gray-500">
            {t(`members.roleHints.${humanRole}`, { defaultValue: '' })}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" disabled={invite.isPending || !email.trim()} className="btn btn-primary">
              {invite.isPending ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />}
              {invite.isPending
                ? t('members.inviting', { defaultValue: 'Inviting…' })
                : t('members.invite', { defaultValue: 'Invite' })}
            </button>
            {invited && (
              <span role="status" className="text-sm text-status-success">
                {t('members.invited', { email: invited.email, role: t(`members.roles.${invited.role}`, { defaultValue: invited.role }), defaultValue: '{{email}} can now work here as {{role}}.' })}
              </span>
            )}
          </div>
          {invite.isError && (
            <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
              <span>{errorMessage}</span>
              <button type="button" onClick={submit} className="underline">{t('common.retry')}</button>
            </div>
          )}
        </form>
      )}
    </div>
  )
}
