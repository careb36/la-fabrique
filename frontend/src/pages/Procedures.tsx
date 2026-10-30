import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookCheck, Check, Loader2, Plus, X } from 'lucide-react'
import { useAgents, useCreateProcedure, useCurrentRole, useDecideProcedure, useProcedures } from '../hooks/useQueries'
import { ALL_ROLES, ApiError, errorDetail, type Procedure, type ProcedureMetrics } from '../services/api'
import { useAppStore } from '../store/useAppStore'

const RESULT_STYLES: Record<string, string> = {
  kept: 'text-emerald-300',
  reverted: 'text-red-300',
  unmeasured: 'text-gray-400',
  superseded: 'text-gray-400',
  restored: 'text-sky-300',
  retired: 'text-gray-400',
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`
}

/**
 * The company's procedures: the rules each role follows. The ScrumMaster
 * proposes them after a sprint with rework or blocked tasks; a Manager adopts
 * or rejects them (with autonomy level 3 they are adopted directly). After two
 * more sprints the board's numbers keep or revert each one.
 */
export default function Procedures() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const role = useCurrentRole()
  const canDecide = role === 'Owner' || role === 'Manager'
  const query = useProcedures(companyId)
  const all = query.data?.procedures ?? []
  const proposed = all.filter(p => p.status === 'proposed')
  const active = all.filter(p => p.status === 'active')
  const history = all.filter(p => p.status === 'rejected' || p.status === 'retired')

  return (
    <div className="page-container max-w-4xl space-y-6">
      <div className="page-header">
        <div>
          <div className="flex items-center gap-2">
            <BookCheck className="text-brand-400" size={22} />
            <h1 className="page-title">{t('procedures.title', { defaultValue: 'Procedures' })}</h1>
          </div>
          <p className="text-gray-400 mt-1">
            {t('procedures.subtitle', { defaultValue: 'The rules each role follows. The ScrumMaster proposes them after a sprint with rework; the board\'s numbers keep or revert them.' })}
          </p>
        </div>
      </div>

      {query.isLoading ? (
        <div role="status" className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={15} className="animate-spin" /> {t('procedures.loading', { defaultValue: 'Loading procedures…' })}
        </div>
      ) : query.isError ? (
        <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
          <span>{t('procedures.loadError', { message: errorDetail(query.error), defaultValue: 'Could not load the procedures: {{message}}' })}</span>
          <button type="button" onClick={() => query.refetch()} className="underline">{t('common.retry')}</button>
        </div>
      ) : (
        <>
          <Section id="proposed" title={t('procedures.proposed', { defaultValue: 'Waiting for a decision' })}
            empty={t('procedures.noProposed', { defaultValue: 'No proposals waiting.' })} items={proposed}
            render={p => <ProcedureCard key={p.id} procedure={p} actions={canDecide ? ['adopt', 'reject'] : []} />} />
          <Section id="active" title={t('procedures.active', { defaultValue: 'In force' })}
            empty={t('procedures.noActive', { defaultValue: 'No procedures in force yet.' })} items={active}
            render={p => <ProcedureCard key={p.id} procedure={p} actions={canDecide ? ['retire'] : []} />} />
          {canDecide && companyId !== null && <NewProcedure companyId={companyId} />}
          <Section id="history" title={t('procedures.history', { defaultValue: 'History' })}
            empty={t('procedures.noHistory', { defaultValue: 'Nothing retired or rejected yet.' })} items={history}
            render={p => <ProcedureCard key={p.id} procedure={p} actions={[]} />} />
        </>
      )}
    </div>
  )
}

function Section({ id, title, empty, items, render }: {
  id: string
  title: string
  empty: string
  items: Procedure[]
  render: (procedure: Procedure) => React.ReactNode
}) {
  return (
    <section aria-labelledby={`procedures-${id}`} className="space-y-2">
      <h2 id={`procedures-${id}`} className="text-sm font-semibold text-white">{title}</h2>
      {items.length === 0 ? <p className="text-sm text-gray-500">{empty}</p> : <ul className="space-y-2">{items.map(render)}</ul>}
    </section>
  )
}

type Decision = 'adopt' | 'reject' | 'retire'

function ProcedureCard({ procedure, actions }: { procedure: Procedure; actions: Decision[] }) {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const decide = useDecideProcedure(companyId)
  const roleLabel = procedure.role === ALL_ROLES ? t('procedures.everyRole', { defaultValue: 'Every role' }) : procedure.role
  const result = procedure.outcome?.result

  return (
    <li className="card p-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
        <span className="badge">{roleLabel}</span>
        <span className="font-semibold text-white">{procedure.title}</span>
        <span>{t('procedures.version', { version: procedure.version, defaultValue: 'v{{version}}' })}</span>
        {result && (
          <span className={`ml-auto font-semibold ${RESULT_STYLES[result] ?? 'text-gray-400'}`}>
            {t(`procedures.results.${result}`, { defaultValue: result })}
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-gray-200">{procedure.body}</p>
      {procedure.rationale && (
        <p className="text-xs text-gray-400">
          {t('procedures.why', { why: procedure.rationale, defaultValue: 'Why: {{why}}' })}
        </p>
      )}
      <p className="text-xs text-gray-500">
        {t('procedures.proposedBy', { who: procedure.proposed_by, defaultValue: 'Proposed by {{who}}' })}
        {procedure.decided_by && ` · ${t('procedures.decidedBy', { who: procedure.decided_by, defaultValue: 'decided by {{who}}' })}`}
      </p>
      <Numbers baseline={procedure.baseline} outcome={procedure.outcome} status={procedure.status} />
      {actions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {actions.map(decision => (
            <button key={decision} type="button" disabled={decide.isPending}
              onClick={() => decide.mutate({ id: procedure.id, decision })}
              className={decision === 'adopt' ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}>
              {decision === 'adopt' ? <Check size={14} /> : <X size={14} />}
              {t(`procedures.actions.${decision}`)}
            </button>
          ))}
          {decide.isError && (
            <span role="alert" className="text-xs text-red-300">
              {decide.error instanceof ApiError && decide.error.status === 409
                ? t('procedures.changed', { defaultValue: 'Someone already decided this one. Reload to see it.' })
                : t('procedures.decideError', { message: errorDetail(decide.error), defaultValue: 'Could not save the decision: {{message}}' })}
            </span>
          )}
        </div>
      )}
    </li>
  )
}

function Numbers({ baseline, outcome, status }: {
  baseline: ProcedureMetrics | null
  outcome: ProcedureMetrics | null
  status: Procedure['status']
}) {
  const { t } = useTranslation()
  if (!baseline) return null
  const measured = outcome && ['kept', 'reverted'].includes(outcome.result ?? '') ? outcome : null
  return (
    <p className="text-xs text-gray-400">
      {t('procedures.before', {
        rework: baseline.rework_per_task,
        blocked: percent(baseline.blocked_rate),
        sprints: baseline.sprints,
        defaultValue: 'Before: {{rework}} rework requests per task, {{blocked}} blocked ({{sprints}} sprints).',
      })}
      {' '}
      {measured
        ? t('procedures.after', {
          rework: measured.rework_per_task,
          blocked: percent(measured.blocked_rate),
          sprints: measured.sprints,
          defaultValue: 'After: {{rework}} per task, {{blocked}} blocked ({{sprints}} sprints).',
        })
        : status === 'active' && !outcome
          ? t('procedures.measuring', { defaultValue: 'Measured after the next two completed sprints.' })
          : null}
    </p>
  )
}

function NewProcedure({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const { data } = useAgents(companyId)
  const create = useCreateProcedure()
  const roles = [ALL_ROLES, ...Array.from(new Set((data?.agents ?? []).map(agent => agent.role).filter(Boolean))).sort()]
  const [role, setRole] = useState(ALL_ROLES)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')

  function submit() {
    if (!title.trim() || !body.trim()) return
    create.mutate(
      { company_id: companyId, role, title: title.trim(), body: body.trim() },
      { onSuccess: () => { setTitle(''); setBody('') } },
    )
  }

  return (
    <section aria-labelledby="procedures-new" className="card p-4 space-y-3">
      <h2 id="procedures-new" className="text-sm font-semibold text-white">{t('procedures.newTitle', { defaultValue: 'Write a procedure' })}</h2>
      <p className="text-xs text-gray-500">
        {t('procedures.newHint', { defaultValue: 'It is in force at once, and measured like the ones the ScrumMaster proposes.' })}
      </p>
      <form onSubmit={e => { e.preventDefault(); submit() }} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-[auto_1fr]">
          <label className="block">
            <span className="input-label">{t('procedures.role', { defaultValue: 'Role' })}</span>
            <select value={role} onChange={e => setRole(e.target.value)} className="select w-full">
              {roles.map(value => (
                <option key={value} value={value}>{value === ALL_ROLES ? t('procedures.everyRole', { defaultValue: 'Every role' }) : value}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="input-label">{t('procedures.titleLabel', { defaultValue: 'Title' })}</span>
            <input value={title} onChange={e => setTitle(e.target.value)} maxLength={120} required className="input w-full" />
          </label>
        </div>
        <label className="block">
          <span className="input-label">{t('procedures.body', { defaultValue: 'The rule' })}</span>
          <textarea value={body} onChange={e => setBody(e.target.value)} maxLength={2000} required rows={3} className="input w-full" />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={create.isPending || !title.trim() || !body.trim()} className="btn btn-primary">
            {create.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
            {t('procedures.create', { defaultValue: 'Put in force' })}
          </button>
          {create.isError && (
            <span role="alert" className="text-sm text-red-300">
              {create.error instanceof ApiError && create.error.status === 409
                ? t('procedures.duplicate', { defaultValue: 'That procedure is already in force or proposed.' })
                : t('procedures.createError', { message: errorDetail(create.error), defaultValue: 'Could not save it: {{message}}' })}
            </span>
          )}
        </div>
      </form>
    </section>
  )
}
