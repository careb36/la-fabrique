import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, LifeBuoy, Loader2, Save } from 'lucide-react'
import { useSupportAgentRecord, useTicket, useTickets, useUpdateTicket } from '../hooks/useQueries'
import { useAuthStore } from '../store/useAuthStore'
import {
  api,
  ApiError,
  errorDetail,
  type AgentRecordField,
  type SupportTicketDetail,
  type TicketCategory,
  type TicketFilters,
  type TicketSeverity,
  type TicketStatus,
} from '../services/api'

const STATUSES: TicketStatus[] = ['open', 'in_progress', 'waiting', 'resolved', 'closed']
const SEVERITIES: TicketSeverity[] = ['critical', 'high', 'medium', 'low']
const CATEGORIES: TicketCategory[] = ['bug', 'feature', 'question', 'incident']
// The fields a support admin decides and the Support agent is measured on.
const RECORD_FIELDS = ['severity', 'category'] as const
// Statuses that close a ticket; the API documents a resolution as mandatory for them.
const TERMINAL: TicketStatus[] = ['resolved', 'closed']

/** The backend's own file name, used when its Content-Disposition is not readable. */
function logFilename(): string {
  return `fabrique_support_logs_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.jsonl`
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

/**
 * Help desk: triage the tickets reported through the support bot. Only support
 * admins (the backend's SUPPORT_ADMIN_EMAILS) see every ticket and change them.
 */
export default function HelpDesk() {
  const { t } = useTranslation()
  const canTriage = useAuthStore(state => Boolean(state.user?.support_admin))
  const [filters, setFilters] = useState<TicketFilters>({})
  const [selected, setSelected] = useState<string | null>(null)

  return (
    <div className="page-container space-y-6">
      <div className="page-header flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <LifeBuoy className="text-brand-400" size={22} />
            <h1 className="page-title">{t('helpDesk.title', { defaultValue: 'Help desk' })}</h1>
          </div>
          <p className="text-gray-400 mt-1">
            {t('helpDesk.subtitle', { defaultValue: 'Problems reported through the support assistant.' })}
          </p>
        </div>
        {canTriage && <LogsDownload />}
      </div>
      {canTriage && <AgentRecord />}
      {!canTriage ? (
        <div role="status" className="card p-4 text-sm text-gray-300">
          {t('helpDesk.adminOnly', { defaultValue: 'The help desk is for support admins. An administrator can add your email to SUPPORT_ADMIN_EMAILS in the backend.' })}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <TicketList filters={filters} onFilters={setFilters} selected={selected} onSelect={setSelected} />
          {selected
            ? <TicketPanel key={selected} ticketNum={selected} />
            : <p className="card p-4 text-sm text-gray-400">{t('helpDesk.pick', { defaultValue: 'Pick a ticket to see its details.' })}</p>}
        </div>
      )}
    </div>
  )
}

function TicketList({ filters, onFilters, selected, onSelect }: {
  filters: TicketFilters
  onFilters: (filters: TicketFilters) => void
  selected: string | null
  onSelect: (ticketNum: string) => void
}) {
  const { t } = useTranslation()
  const [email, setEmail] = useState(filters.reporter_email ?? '')
  const tickets = useTickets(filters)
  const rows = tickets.data?.tickets ?? []

  return (
    <section className="card min-w-0 p-4 space-y-3" aria-labelledby="tickets-title">
      <h2 id="tickets-title" className="text-sm font-semibold text-white">{t('helpDesk.tickets', { defaultValue: 'Tickets' })}</h2>
      <form className="grid gap-2 sm:grid-cols-3"
        onSubmit={e => { e.preventDefault(); onFilters({ ...filters, reporter_email: email.trim() || undefined }) }}>
        <label className="block">
          <span className="input-label">{t('helpDesk.status', { defaultValue: 'Status' })}</span>
          <select className="select w-full" value={filters.status ?? ''}
            onChange={e => onFilters({ ...filters, status: (e.target.value || undefined) as TicketStatus | undefined })}>
            <option value="">{t('helpDesk.any', { defaultValue: 'Any' })}</option>
            {STATUSES.map(value => <option key={value} value={value}>{t(`support.status.${value}`)}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="input-label">{t('helpDesk.severity', { defaultValue: 'Impact' })}</span>
          <select className="select w-full" value={filters.severity ?? ''}
            onChange={e => onFilters({ ...filters, severity: (e.target.value || undefined) as TicketSeverity | undefined })}>
            <option value="">{t('helpDesk.any', { defaultValue: 'Any' })}</option>
            {SEVERITIES.map(value => <option key={value} value={value}>{t(`helpDesk.severities.${value}`)}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="input-label">{t('helpDesk.reporter', { defaultValue: 'Reporter email' })}</span>
          <input type="email" className="input w-full" value={email} onChange={e => setEmail(e.target.value)}
            onBlur={() => onFilters({ ...filters, reporter_email: email.trim() || undefined })}
            placeholder={t('support.emailPlaceholder')} />
        </label>
      </form>

      {tickets.isLoading ? (
        <div role="status" className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={15} className="animate-spin" /> {t('helpDesk.loading', { defaultValue: 'Loading tickets…' })}
        </div>
      ) : tickets.isError ? (
        <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
          <span>{t('helpDesk.loadError', { message: errorDetail(tickets.error), defaultValue: 'Could not load the tickets: {{message}}' })}</span>
          <button type="button" onClick={() => tickets.refetch()} className="underline">{t('common.retry')}</button>
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-400">{t('helpDesk.empty', { defaultValue: 'No tickets match these filters.' })}</p>
      ) : (
        <ul className="divide-y divide-surface-700">
          {rows.map(ticket => (
            <li key={ticket.ticket_num}>
              <button type="button" onClick={() => onSelect(ticket.ticket_num)}
                aria-current={selected === ticket.ticket_num ? 'true' : undefined}
                className={`w-full rounded px-2 py-2 text-left hover:bg-surface-800 ${selected === ticket.ticket_num ? 'bg-surface-800' : ''}`}>
                <span className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
                  <span className="font-mono text-gray-300">{ticket.ticket_num}</span>
                  <span className="badge">{t(`support.status.${ticket.status}`, { defaultValue: ticket.status })}</span>
                  {/* The impact a support admin decided, else the reporter's choice, marked as such: what the Impact filter reads. */}
                  <span>{ticket.decided_severity
                    ? t(`helpDesk.severities.${ticket.decided_severity}`, { defaultValue: ticket.decided_severity })
                    : ticket.severity
                      ? t('helpDesk.reportedImpact', { severity: t(`helpDesk.severities.${ticket.severity}`, { defaultValue: ticket.severity }) })
                      : '—'}</span>
                  <span className="ml-auto">{formatDate(ticket.created_at)}</span>
                </span>
                <span className="mt-0.5 block truncate text-sm text-white">{ticket.title}</span>
                {ticket.reporter_email && <span className="block truncate text-xs text-gray-500">{ticket.reporter_email}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function TicketPanel({ ticketNum }: { ticketNum: string }) {
  const { t } = useTranslation()
  const ticket = useTicket(ticketNum)

  if (ticket.isLoading) {
    return (
      <div role="status" className="card p-4 flex items-center gap-2 text-sm text-gray-400">
        <Loader2 size={15} className="animate-spin" /> {t('helpDesk.loadingTicket', { defaultValue: 'Loading the ticket…' })}
      </div>
    )
  }
  if (ticket.isError || !ticket.data) {
    return (
      <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
        <span>{t('helpDesk.ticketError', { message: errorDetail(ticket.error), defaultValue: 'Could not load the ticket: {{message}}' })}</span>
        <button type="button" onClick={() => ticket.refetch()} className="underline">{t('common.retry')}</button>
      </div>
    )
  }
  return <TicketDetail ticket={ticket.data} />
}

function TicketDetail({ ticket }: { ticket: SupportTicketDetail }) {
  const { t } = useTranslation()
  const fields: { key: string; label: string; value: string | null }[] = [
    { key: 'description', label: t('helpDesk.description', { defaultValue: 'What happened' }), value: ticket.description },
    { key: 'steps', label: t('helpDesk.steps', { defaultValue: 'Steps' }), value: ticket.steps },
    { key: 'expected', label: t('helpDesk.expected', { defaultValue: 'Expected' }), value: ticket.expected },
    { key: 'actual', label: t('helpDesk.actual', { defaultValue: 'Actual' }), value: ticket.actual },
    { key: 'resolution', label: t('support.resolution'), value: ticket.resolution },
  ]
  return (
    <section className="card min-w-0 p-4 space-y-4" aria-labelledby="ticket-title">
      <div>
        <p className="font-mono text-xs text-gray-400">{ticket.ticket_num}</p>
        <h2 id="ticket-title" className="text-base font-semibold text-white break-words">{ticket.title}</h2>
        <p className="text-xs text-gray-500">
          {t('helpDesk.meta', {
            reporter: ticket.reporter_email ?? '—',
            created: formatDate(ticket.created_at),
            assignee: ticket.assigned_to ?? '—',
            defaultValue: 'Reported by {{reporter}} on {{created}} · assigned to {{assignee}}',
          })}
        </p>
      </div>
      <dl className="space-y-3">
        {fields.filter(field => field.value).map(field => (
          <div key={field.key}>
            <dt className="text-xs font-semibold text-gray-500">{field.label}</dt>
            <dd className="whitespace-pre-wrap break-words text-sm text-gray-200">{field.value}</dd>
          </div>
        ))}
      </dl>
      {ticket.triaged_by && (
        <div className="rounded-lg border border-surface-700 p-3 text-sm" aria-label={t('helpDesk.triage', { defaultValue: 'Triage' })}>
          <p className="mb-1 text-xs font-semibold text-gray-400">
            {t('helpDesk.triagedBy', { who: ticket.triaged_by, defaultValue: 'Triage by {{who}} (suggestions; the reporter chose the severity)' })}
          </p>
          {ticket.suggested_severity ? (
            <>
              <p className="text-xs text-gray-300">
                {t('helpDesk.suggested', {
                  severity: t(`helpDesk.severities.${ticket.suggested_severity}`, { defaultValue: ticket.suggested_severity }),
                  category: ticket.suggested_category ?? '—',
                  reported: ticket.severity ? t(`helpDesk.severities.${ticket.severity}`, { defaultValue: ticket.severity }) : '—',
                  defaultValue: 'Suggested impact: {{severity}} (reported: {{reported}}) · category: {{category}}',
                })}
              </p>
              {ticket.agent_reply && (
                <>
                  <p className="mt-2 text-xs font-semibold text-gray-400">{t('helpDesk.agentReply', { defaultValue: 'First reply sent to the reporter' })}</p>
                  <p className="whitespace-pre-wrap break-words text-gray-200">{ticket.agent_reply}</p>
                </>
              )}
            </>
          ) : (
            <p className="text-xs text-gray-400">{t('helpDesk.untriaged', { defaultValue: 'The agent could not triage this ticket; it is left to people.' })}</p>
          )}
        </div>
      )}
      {ticket.decided_by && (
        <p className="text-xs text-gray-300">
          {t('helpDesk.decided', {
            severity: ticket.decided_severity ? t(`helpDesk.severities.${ticket.decided_severity}`, { defaultValue: ticket.decided_severity }) : '—',
            category: ticket.decided_category ? t(`helpDesk.categories.${ticket.decided_category}`, { defaultValue: ticket.decided_category }) : '—',
            who: ticket.decided_by,
            defaultValue: 'Decided: impact {{severity}} · category {{category}}, last changed by {{who}}',
          })}
        </p>
      )}
      <UpdateForm ticket={ticket} />
    </section>
  )
}

interface TicketForm {
  status: TicketStatus
  resolution: string
  assignee: string
  severity: TicketSeverity | ''
  category: TicketCategory | ''
}

function UpdateForm({ ticket }: { ticket: SupportTicketDetail }) {
  const { t } = useTranslation()
  const update = useUpdateTicket()
  // What the ticket stores, as the form shows it. The admin's decision is
  // the ticket's current one, never the reporter's choice or the agent's
  // suggestion: leaving it empty decides nothing.
  const stored: TicketForm = {
    status: STATUSES.includes(ticket.status as TicketStatus) ? ticket.status as TicketStatus : 'open',
    resolution: ticket.resolution ?? '',
    assignee: ticket.assigned_to ?? '',
    severity: SEVERITIES.includes(ticket.decided_severity as TicketSeverity) ? ticket.decided_severity as TicketSeverity : '',
    category: CATEGORIES.includes(ticket.decided_category as TicketCategory) ? ticket.decided_category as TicketCategory : '',
  }
  // The fields edited since the last save, kept apart from the ticket: the
  // rest follow what another admin saves meanwhile (a ticket they resolved
  // is not reopened, their decision is not sent again in this admin's name),
  // and a field put back to what the ticket stores counts as untouched.
  const [edits, setEdits] = useState<Partial<TicketForm>>({})
  const form: TicketForm = { ...stored, ...edits }
  const needsResolution = TERMINAL.includes(form.status) && !form.resolution.trim()

  function edit<K extends keyof TicketForm>(field: K, value: TicketForm[K]) {
    setEdits(current => {
      const next = { ...current }
      if (value === stored[field]) delete next[field]
      else next[field] = value
      return next
    })
  }

  function submit() {
    if (needsResolution) return
    const sent = edits
    update.mutate({
      ticketNum: ticket.ticket_num,
      data: {
        status: form.status,
        ...(form.resolution.trim() ? { resolution: form.resolution.trim() } : {}),
        ...(form.assignee.trim() ? { assigned_to: form.assignee.trim() } : {}),
        // Only a decision edited here is sent ('' clears one), so saving the
        // status does not decide again in the saver's name.
        ...('severity' in sent ? { severity: sent.severity } : {}),
        ...('category' in sent ? { category: sent.category } : {}),
      },
    }, {
      // Saved, and the ticket refetched: the form shows what is stored, except
      // a field the admin changed again while the save was on its way.
      onSuccess: () => setEdits(current => Object.fromEntries(
        Object.entries(current).filter(([field, value]) => value !== sent[field as keyof TicketForm]),
      ) as Partial<TicketForm>),
    })
  }

  return (
    <form onSubmit={e => { e.preventDefault(); submit() }} className="space-y-3 border-t border-surface-700 pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="input-label">{t('helpDesk.newStatus', { defaultValue: 'Status' })}</span>
          <select className="select w-full" value={form.status} onChange={e => edit('status', e.target.value as TicketStatus)}>
            {STATUSES.map(value => <option key={value} value={value}>{t(`support.status.${value}`)}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="input-label">{t('helpDesk.assignee', { defaultValue: 'Assigned to' })}</span>
          <input className="input w-full" value={form.assignee} onChange={e => edit('assignee', e.target.value)} />
        </label>
        <label className="block">
          <span className="input-label">{t('helpDesk.decidedSeverity', { defaultValue: 'Decided impact' })}</span>
          <select className="select w-full" value={form.severity} onChange={e => edit('severity', e.target.value as TicketSeverity | '')}>
            <option value="">{t('helpDesk.notDecided', { defaultValue: 'Not decided' })}</option>
            {SEVERITIES.map(value => <option key={value} value={value}>{t(`helpDesk.severities.${value}`)}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="input-label">{t('helpDesk.decidedCategory', { defaultValue: 'Decided category' })}</span>
          <select className="select w-full" value={form.category} onChange={e => edit('category', e.target.value as TicketCategory | '')}>
            <option value="">{t('helpDesk.notDecided', { defaultValue: 'Not decided' })}</option>
            {CATEGORIES.map(value => <option key={value} value={value}>{t(`helpDesk.categories.${value}`)}</option>)}
          </select>
        </label>
      </div>
      <label className="block">
        <span className="input-label">{t('support.resolution')}</span>
        <textarea className="input w-full" rows={3} value={form.resolution} onChange={e => edit('resolution', e.target.value)}
          aria-invalid={needsResolution || undefined} />
      </label>
      {needsResolution && (
        <p className="text-xs text-amber-300">
          {t('helpDesk.resolutionRequired', { defaultValue: 'Write the resolution before resolving or closing the ticket.' })}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={update.isPending || needsResolution} className="btn btn-primary">
          {update.isPending ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
          {update.isPending ? t('helpDesk.saving', { defaultValue: 'Saving…' }) : t('helpDesk.save', { defaultValue: 'Save' })}
        </button>
        {update.isSuccess && (
          <span role="status" className="text-sm text-status-success">{t('helpDesk.saved', { defaultValue: 'Ticket updated' })}</span>
        )}
      </div>
      {update.isError && (
        <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
          <span>{t('helpDesk.saveError', { message: errorDetail(update.error), defaultValue: 'Could not update the ticket: {{message}}' })}</span>
          <button type="button" onClick={submit} className="underline">{t('common.retry')}</button>
        </div>
      )}
    </form>
  )
}

/**
 * How the Support agent's suggestions compared with what support admins
 * decided, beside how the reporters' own choices did: the agent's triage is a
 * claim, and this is what the tickets say about it.
 */
function AgentRecord() {
  const { t } = useTranslation()
  const record = useSupportAgentRecord(true)
  if (!record.data || (record.data.severity.decided === 0 && record.data.category.decided === 0)) return null
  const line = (key: typeof RECORD_FIELDS[number], field: AgentRecordField) => field.decided > 0 && (
    <p key={key} className="text-xs text-gray-300">
      {t(`helpDesk.record.${key}`, {
        agent: field.agent_agreed,
        total: field.decided,
        defaultValue: key === 'severity'
          ? 'Impact: the agent matched {{agent}} of {{total}} decisions'
          : 'Category: the agent matched {{agent}} of {{total}} decisions',
      })}
      {field.agent_unusable > 0 && t('helpDesk.record.unusable', {
        n: field.agent_unusable,
        defaultValue: ' ({{n}} without a usable answer)',
      })}
      {field.reporter_chose > 0
        ? t('helpDesk.record.reporters', {
          reporter: field.reporter_agreed,
          chose: field.reporter_chose,
          defaultValue: '; the reporters {{reporter}} of {{chose}}.',
        })
        : t('helpDesk.record.noReporters', { defaultValue: '; no reporter chose one.' })}
    </p>
  )
  return (
    <section className="card space-y-1 p-4" aria-label={t('helpDesk.record.title', { defaultValue: "The Support agent's record" })}>
      <h2 className="text-sm font-semibold text-white">{t('helpDesk.record.title', { defaultValue: "The Support agent's record" })}</h2>
      {RECORD_FIELDS.map(key => line(key, record.data[key]))}
    </section>
  )
}

function LogsDownload() {
  const { t } = useTranslation()
  const [state, setState] = useState<'idle' | 'loading' | 'missing' | 'error'>('idle')
  const [message, setMessage] = useState('')

  async function download() {
    setState('loading')
    try {
      const { blob, filename } = await api.downloadSupportLogs()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename ?? logFilename()
      link.click()
      URL.revokeObjectURL(url)
      setState('idle')
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setState('missing')
      } else {
        setMessage(errorDetail(error))
        setState('error')
      }
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button type="button" onClick={() => { void download() }} disabled={state === 'loading'} className="btn btn-secondary btn-sm">
        {state === 'loading' ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
        {t('helpDesk.downloadLogs', { defaultValue: 'Download logs' })}
      </button>
      {state === 'missing' && (
        <p role="status" className="text-xs text-gray-400">{t('helpDesk.noLogs', { defaultValue: 'No logs have been written yet.' })}</p>
      )}
      {state === 'error' && (
        <p role="alert" className="text-xs text-red-300">
          {t('helpDesk.logsError', { message, defaultValue: 'Could not download the logs: {{message}}' })}
        </p>
      )}
    </div>
  )
}
