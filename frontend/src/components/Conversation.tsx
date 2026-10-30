import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowRight, MessagesSquare } from 'lucide-react'
import { useAgentMessages } from '../hooks/useQueries'
import { MESSAGE_KINDS, type AgentMessage, type MessageKind } from '../services/api'
import { SkeletonBlock } from './Skeleton'

const KIND_STYLES: Record<MessageKind, string> = {
  question: 'border-sky-700/60 text-sky-300',
  answer: 'border-sky-700/60 text-sky-200',
  handoff: 'border-surface-600 text-gray-300',
  request: 'border-amber-700/60 text-amber-300',
  decision: 'border-emerald-700/60 text-emerald-300',
  escalation: 'border-red-700/60 text-red-300',
  retrospective: 'border-brand-700/60 text-brand-300',
  proposal: 'border-violet-700/60 text-violet-300',
}
const LONG_BODY = 400
// While work is moving, new messages appear without a reload.
const REFRESH_MS = 10_000

/**
 * The conversation between the company's agents: who said what to whom, in
 * order. Messages are what roles said (claims); the evidence pages show what
 * was verified.
 */
export function Conversation({ companyId, sprintId, taskId, live = false }: {
  companyId: number
  sprintId?: number
  taskId?: number
  live?: boolean
}) {
  const { t } = useTranslation()
  const [kind, setKind] = useState<MessageKind | ''>('')
  const query = useAgentMessages(
    companyId,
    {
      ...(sprintId !== undefined ? { sprint_id: sprintId } : {}),
      ...(taskId !== undefined ? { backlog_item_id: taskId } : {}),
      ...(kind ? { kind } : {}),
    },
    live ? REFRESH_MS : false,
  )
  const messages = query.data?.messages ?? []
  const perTask = taskId !== undefined

  return (
    <section aria-labelledby={perTask ? 'task-conversation-title' : 'conversation-title'} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h2 id={perTask ? 'task-conversation-title' : 'conversation-title'}
            className="flex items-center gap-2 text-sm font-semibold text-white">
            <MessagesSquare size={15} aria-hidden="true" /> {t('conversation.title', { defaultValue: 'Conversation' })}
          </h2>
          <p className="text-xs text-gray-500">
            {t('conversation.claimsNote', { defaultValue: 'What the roles said to each other. The evidence shows what was verified.' })}
          </p>
        </div>
        {!perTask && (
          <label className="text-xs text-gray-400">
            <span className="mr-2">{t('conversation.kindFilter', { defaultValue: 'Show' })}</span>
            <select value={kind} onChange={e => setKind(e.target.value as MessageKind | '')} className="select py-1 text-xs">
              <option value="">{t('conversation.allKinds', { defaultValue: 'All messages' })}</option>
              {MESSAGE_KINDS.map(value => (
                <option key={value} value={value}>{t(`conversation.kinds.${value}`)}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {query.isLoading ? (
        <div role="status" aria-label={t('conversation.loading', { defaultValue: 'Loading the conversation…' })}>
          <SkeletonBlock className="h-16" />
        </div>
      ) : query.isError ? (
        <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
          <span>{t('conversation.error', { defaultValue: 'Could not load the conversation.' })}</span>
          <button type="button" onClick={() => query.refetch()} className="underline">{t('common.retry')}</button>
        </div>
      ) : messages.length === 0 ? (
        <p className="text-sm text-gray-400">
          {kind
            ? t('conversation.emptyKind', { defaultValue: 'No messages of this kind yet.' })
            : t('conversation.empty', { defaultValue: 'No messages yet. They appear as the roles hand work to each other.' })}
        </p>
      ) : (
        <ol className="space-y-2">
          {messages.map(message => (
            <MessageItem key={message.id} message={message} showTask={!perTask} />
          ))}
        </ol>
      )}
    </section>
  )
}

function MessageItem({ message, showTask }: { message: AgentMessage; showTask: boolean }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const long = message.body.length > LONG_BODY
  const body = long && !expanded ? `${message.body.slice(0, LONG_BODY)}…` : message.body
  const recipient = message.to_role ?? t('conversation.team', { defaultValue: 'the team' })

  return (
    <li className="card p-3">
      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="font-semibold text-white">{message.from_name}</span>
        {message.from_name !== message.from_role && <span className="text-gray-500">{message.from_role}</span>}
        <ArrowRight size={12} className="text-gray-500" aria-label={t('conversation.to', { defaultValue: 'to' })} />
        <span className="text-gray-300">{recipient}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${KIND_STYLES[message.kind] ?? KIND_STYLES.handoff}`}>
          {t(`conversation.kinds.${message.kind}`, { defaultValue: message.kind })}
        </span>
        {message.created_at && (
          <time dateTime={message.created_at} className="ml-auto text-gray-500">
            {new Date(message.created_at).toLocaleString()}
          </time>
        )}
      </div>
      {showTask && message.task_title && message.sprint_id !== null && message.backlog_item_id !== null && (
        <Link to={`/sprints/${message.sprint_id}/tasks/${message.backlog_item_id}`}
          className="mb-1 block truncate text-xs text-brand-300 hover:underline">
          {message.task_title}
        </Link>
      )}
      <p className="whitespace-pre-wrap break-words text-sm text-gray-200">{body}</p>
      {long && (
        <button type="button" onClick={() => setExpanded(value => !value)} className="mt-1 text-xs text-gray-400 underline">
          {expanded ? t('conversation.showLess', { defaultValue: 'Show less' }) : t('conversation.showMore', { defaultValue: 'Show more' })}
        </button>
      )}
    </li>
  )
}
