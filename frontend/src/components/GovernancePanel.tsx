import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { AlertTriangle, BookCheck, CheckCircle2, Loader2, PauseOctagon, RefreshCw, ShieldAlert, ShieldCheck, Undo2 } from 'lucide-react'
import { useAgentRuns, useCurrentRole, useInbox, useReviewerRecord, useSprints, useUpdateBacklogItem } from '../hooks/useQueries'
import { secondAttempts } from '../lib/learningTrend'
import { useAppStore } from '../store/useAppStore'
import { ALL_ROLES, errorDetail, type AgentRunListItem, type InboxBlockedTask, type InboxProposal } from '../services/api'

// The note written on the task when a person sends it back to work. Not
// translated: the backend recognises it (services/board.py SEND_BACK_MARKER)
// and restarts the rework budgets after it.
const SEND_BACK_COMMENT = 'Sent back to work by a person.'
// The note written when a person accepts an approved high-risk delivery.
const ACCEPT_COMMENT = 'High-risk delivery accepted by a person.'

/**
 * The company's agents do the work; this page is what they need a person
 * for: tasks blocked until someone acts, procedure proposals waiting for a
 * Manager, and runs nobody has decided on.
 */
function Section({ id, title, count, children }: { id: string; title: string; count: number; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`inbox-${id}`} className="space-y-3">
      <h2 id={`inbox-${id}`} className="flex items-center gap-2 text-sm font-semibold text-white">
        {title}
        {count > 0 && <span className="badge">{count}</span>}
      </h2>
      {children}
    </section>
  )
}

function BlockedTask({ task, canManage }: { task: InboxBlockedTask; canManage: boolean }) {
  const { t } = useTranslation()
  const update = useUpdateBacklogItem()
  const accept = useUpdateBacklogItem()
  const sendBack = () => update.mutate({
    itemId: task.id,
    data: { status: 'todo', comment: SEND_BACK_COMMENT },
  })
  const acceptDelivery = () => accept.mutate({
    itemId: task.id,
    data: { status: 'done', comment: ACCEPT_COMMENT },
  })
  const pending = update.isPending || accept.isPending

  return (
    <article className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <Link to={`/sprints/${task.sprint_id}/tasks/${task.id}`} className="block truncate text-sm font-semibold text-gray-200 hover:underline">
          {task.title}
        </Link>
        <p className="text-xs text-gray-500">
          {task.sprint_name}
          {task.assignee && ` · ${task.assignee}`}
          {task.frozen && ` · ${t('inbox.frozen', { defaultValue: 'frozen by an operator' })}`}
        </p>
        {task.risk_hold && (
          <p className="flex items-center gap-1 text-xs font-semibold text-amber-300">
            <ShieldAlert size={12} aria-hidden="true" />
            {t('inbox.riskHold', { defaultValue: 'Approved by QA, but high risk: a person accepts it or sends it back.' })}
          </p>
        )}
        {task.reason && <p className="break-words text-xs text-gray-400">{task.reason}</p>}
        {task.triage && (
          <p className="break-words text-xs text-sky-200/80">
            <span className="font-semibold">
              {task.triage.decision === 'retry'
                ? t('inbox.triageRetry', { defaultValue: 'ScrumMaster: another attempt in the next sprint.' })
                : t('inbox.triagePerson', { defaultValue: 'ScrumMaster: leave it for a person.' })}
            </span>
            {task.triage.why && ` ${task.triage.why}`}
            {task.triage.brief && ` ${t('inbox.triageBrief', { brief: task.triage.brief, defaultValue: 'Brief: {{brief}}' })}`}
          </p>
        )}
        {update.isError && (
          <p role="alert" className="text-xs text-red-300">
            {t('inbox.sendBackError', { message: errorDetail(update.error), defaultValue: 'Could not send it back: {{message}}' })}
          </p>
        )}
        {accept.isError && (
          <p role="alert" className="text-xs text-red-300">
            {t('inbox.acceptError', { message: errorDetail(accept.error), defaultValue: 'Could not accept it: {{message}}' })}
          </p>
        )}
      </div>
      {canManage && !task.frozen && (
        <div className="flex shrink-0 gap-2 self-start">
          {task.risk_hold && (
            <button type="button" onClick={acceptDelivery} disabled={pending} className="btn btn-primary btn-sm">
              {accept.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {t('inbox.accept', { defaultValue: 'Accept' })}
            </button>
          )}
          <button type="button" onClick={sendBack} disabled={pending} className="btn btn-secondary btn-sm">
            {update.isPending ? <Loader2 size={14} className="animate-spin" /> : <Undo2 size={14} />}
            {t('inbox.sendBack', { defaultValue: 'Send back to work' })}
          </button>
        </div>
      )}
    </article>
  )
}

function Proposal({ proposal }: { proposal: InboxProposal }) {
  const { t } = useTranslation()
  const role = proposal.role === ALL_ROLES ? t('procedures.everyRole', { defaultValue: 'Every role' }) : proposal.role
  return (
    <article className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-gray-200">{proposal.title}</p>
        <p className="text-xs text-gray-500">
          {t('inbox.proposalMeta', { role, who: proposal.proposed_by, defaultValue: '{{role}} · proposed by {{who}}' })}
        </p>
      </div>
      <Link to="/company/procedures" className="btn btn-primary btn-sm self-start sm:self-auto">
        {t('inbox.decide', { defaultValue: 'Decide' })}
      </Link>
    </article>
  )
}

function PendingRuns({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  // The company's own runs are decided by the review loop; only other
  // producers' runs wait for a person. The server leaves them out (one list of
  // in-house producers, the same the inbox counts by).
  const { data, isLoading, isError, refetch } = useAgentRuns(companyId, { limit: 500, exclude_in_house: true })
  const runs = (data?.agent_runs ?? []).filter(run => run.latest_approval === null)
  // The Reviewer agent's suggestions are claims; this is what the decisions
  // people recorded say about them, beside what the Verifier's verdict alone
  // would have decided.
  const record = useReviewerRecord(companyId).data
  const recordLine = record && record.decided > 0 ? (
    <p role="note" className="text-xs text-gray-400">
      {t('governance.reviewerRecord', { agent: record.agent_agreed, total: record.decided })}
      {record.agent_unusable > 0 && t('governance.reviewerUnusable', { n: record.agent_unusable })}
      {record.verifier_called > 0
        ? t('governance.reviewerVerifier', { verifier: record.verifier_agreed, called: record.verifier_called })
        : t('governance.reviewerVerifierNone')}
    </p>
  ) : null

  if (isLoading) {
    return <div role="status" className="space-y-3" aria-label={t('common.loading')}>
      {[1, 2, 3].map(item => <div key={item} className="skeleton h-20 rounded-lg" />)}
    </div>
  }

  if (isError) {
    return <div role="alert" className="alert-error flex items-center justify-between gap-3">
      <span>{t('governance.fetchError')}</span>
      <button onClick={() => refetch()} className="btn-ghost btn-sm"><RefreshCw size={14} />{t('common.refresh')}</button>
    </div>
  }

  if (runs.length === 0) {
    return <div className="space-y-3">
      {recordLine}
      <div className="empty-state py-8">
        <CheckCircle2 size={32} className="mx-auto mb-3 text-status-success" />
        <p className="font-semibold text-gray-300">{t('governance.noPendingRuns')}</p>
      </div>
    </div>
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-400">{runs.length} {t('governance.pendingRuns')}</p>
      {recordLine}
      {runs.map((run: AgentRunListItem) => (
        <article key={run.id} className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-200">{run.producer}{run.agent_role ? ` · ${run.agent_role}` : ''}</p>
            <p className="truncate font-mono text-xs text-gray-500">{run.external_ref}</p>
            {/* A suggestion is a claim: the decision is taken on the evidence page. */}
            {run.reviewed_by && (
              <p className="mt-1 text-xs text-gray-400">
                {run.suggested_decision
                  ? t('governance.suggestion', { decision: t(`evidence.approval.${run.suggested_decision}`) })
                  : t('governance.suggestionUnusable')}
              </p>
            )}
          </div>
          <Link to={`/evidence/${run.id}`} className="btn btn-primary btn-sm self-start sm:self-auto">
            {t('governance.reviewRun')}
          </Link>
        </article>
      ))}
    </div>
  )
}

function Inbox({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const role = useCurrentRole()
  const canManage = role === 'Owner' || role === 'Manager'
  const inbox = useInbox(companyId)
  const blocked = inbox.data?.blocked_tasks ?? []
  const proposals = inbox.data?.proposals ?? []
  // How earlier second attempts went, counted from the closed sprints' boards:
  // the evidence beside the ScrumMaster's advice when a person decides what to
  // do with a blocked task. Only fetched while there is one to decide on.
  const sprints = useSprints(blocked.length > 0 ? companyId : null)
  const record = secondAttempts(sprints.data ?? [])

  return (
    <div className="space-y-8">
      {inbox.isError && (
        <div role="alert" className="alert-error flex items-center justify-between gap-3">
          <span>{t('inbox.loadError', { message: errorDetail(inbox.error), defaultValue: 'Could not load what needs you: {{message}}' })}</span>
          <button onClick={() => inbox.refetch()} className="btn-ghost btn-sm"><RefreshCw size={14} />{t('common.refresh')}</button>
        </div>
      )}
      <Section id="blocked" title={t('inbox.blockedTitle', { defaultValue: 'Tasks blocked until someone acts' })} count={blocked.length}>
        {inbox.isLoading ? (
          <div role="status" aria-label={t('common.loading')} className="skeleton h-20 rounded-lg" />
        ) : blocked.length === 0 ? (
          <p className="text-sm text-gray-500">{t('inbox.noBlocked', { defaultValue: 'No task is waiting for a person.' })}</p>
        ) : (
          <>
            <p className="flex items-center gap-1.5 text-xs text-gray-500">
              <PauseOctagon size={12} aria-hidden="true" />
              {t('inbox.blockedHint', { defaultValue: 'The agents gave up on these after the rework limit. Send one back to work, or close it on its board.' })}
            </p>
            {record.total > 0 && (
              <p className="text-xs text-gray-400">
                {t('inbox.secondAttemptsRecord', {
                  done: record.done,
                  total: record.total,
                  briefedDone: record.briefed_done,
                  briefed: record.briefed,
                  defaultValue: "So far {{done}} of {{total}} second attempts got done; with the ScrumMaster's brief, {{briefedDone}} of {{briefed}}.",
                })}
              </p>
            )}
            {blocked.map(task => <BlockedTask key={task.id} task={task} canManage={canManage} />)}
          </>
        )}
      </Section>
      <Section id="proposals" title={t('inbox.proposalsTitle', { defaultValue: 'Procedure proposals waiting for a decision' })} count={proposals.length}>
        {inbox.isLoading ? null : proposals.length === 0 ? (
          <p className="text-sm text-gray-500">{t('inbox.noProposals', { defaultValue: 'No proposal is waiting.' })}</p>
        ) : (
          <>
            <p className="flex items-center gap-1.5 text-xs text-gray-500">
              <BookCheck size={12} aria-hidden="true" />
              {t('inbox.proposalsHint', { defaultValue: 'The ScrumMaster proposed these after a sprint with rework or blocked tasks; the board\'s numbers will judge them.' })}
            </p>
            {proposals.map(proposal => <Proposal key={proposal.id} proposal={proposal} />)}
          </>
        )}
      </Section>
      <Section id="runs" title={t('inbox.runsTitle', { defaultValue: 'Runs awaiting a decision' })} count={inbox.data?.pending_runs ?? 0}>
        <PendingRuns companyId={companyId} />
      </Section>
    </div>
  )
}

export const GovernancePanel: React.FC = () => {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <ShieldCheck className="text-brand-400" size={22} />
        <h1 className="text-xl font-bold text-white">{t('nav.review', { defaultValue: 'Review' })}</h1>
      </div>
      <p className="mb-6 text-sm text-gray-400">
        {t('inbox.subtitle', { defaultValue: 'What the company needs you for. The agents do the rest.' })}
      </p>
      {companyId === null
        ? <div className="empty-state py-12"><AlertTriangle size={32} className="mx-auto mb-3 text-gray-500" /><p className="text-gray-400">{t('evidence.selectCompany')}</p></div>
        : <Inbox companyId={companyId} />}
    </div>
  )
}
