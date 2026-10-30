import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, User, Flag, MessageSquare, Clock, ClipboardCheck, RotateCcw } from 'lucide-react'
import { Breadcrumbs } from '../components/Breadcrumbs'
import { Verdict } from '../components/Verdict'
import { Conversation } from '../components/Conversation'
import { useAppStore } from '../store/useAppStore'
import { useAgentRuns, useCapabilities, useSprintBoard } from '../hooks/useQueries'
import { SkeletonBlock, SkeletonLine } from '../components/Skeleton'
import { ApiError, type BacklogItem } from '../services/api'
import { parseRouteId } from '../lib/routeId'
import { carryOverLineage } from '../lib/carryOver'
import { TASK_WORKER_PRODUCER, taskExternalRef } from '../lib/taskEvidence'
import { lineagePath } from './Lineage'

const PRIORITY_STYLES: Record<BacklogItem['priority'], string> = {
  critical: 'bg-red-900/40 text-red-300 border-red-700/40',
  high:     'bg-orange-900/40 text-orange-300 border-orange-700/40',
  medium:   'bg-blue-900/40 text-blue-300 border-blue-700/40',
  low:      'bg-gray-800 text-gray-400 border-surface-600',
}

const STATUS_STYLES: Record<BacklogItem['status'], string> = {
  todo:        'bg-surface-800 text-gray-300 border-surface-700',
  in_progress: 'bg-brand-900/40 text-brand-300 border-brand-700/40',
  in_review:   'bg-yellow-900/40 text-yellow-300 border-yellow-700/40',
  done:        'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  blocked:     'bg-red-900/40 text-red-300 border-red-700/40',
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

/** The latest recorded delivery of this task: its verdict and what it claims. */
function TaskEvidence({ companyId, taskId }: { companyId: number; taskId: number }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useAgentRuns(companyId, {
    producer: TASK_WORKER_PRODUCER,
    external_ref: taskExternalRef(taskId),
    limit: 1,
  })
  const { data: capabilities } = useCapabilities()
  const run = data?.agent_runs[0]
  const files: unknown = run?.claims?.files
  const claimedFiles = Array.isArray(files)
    ? files.filter((file): file is string => typeof file === 'string')
    : []

  return (
    <section aria-labelledby="task-evidence-title" className="card p-4 mb-4">
      <h2 id="task-evidence-title" className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3 flex items-center gap-1">
        <ClipboardCheck size={10} aria-hidden="true" /> {t('taskDetails.evidence.title', { defaultValue: 'Evidence' })}
      </h2>
      {isLoading ? (
        <div role="status" aria-label={t('taskDetails.evidence.loading', { defaultValue: 'Loading evidence…' })}>
          <SkeletonBlock className="h-12" />
        </div>
      ) : isError ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-red-300">
            {t('taskDetails.evidence.error', { defaultValue: 'Failed to load the evidence for this task.' })}
          </p>
          <button onClick={() => refetch()} className="btn btn-ghost btn-sm">{t('common.retry')}</button>
        </div>
      ) : !run ? (
        <p className="text-sm text-gray-400">{t('taskDetails.evidence.empty', { defaultValue: 'No evidence recorded yet.' })}</p>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Verdict status={run.status} />
            <span className="text-xs text-gray-400">
              {t('taskDetails.evidence.version', { version: run.version, defaultValue: 'Version {{version}}' })}
            </span>
            <Link to={`/evidence/${run.id}`} className="btn btn-ghost btn-sm ml-auto">
              {t('taskDetails.evidence.view', { defaultValue: 'View evidence' })}
            </Link>
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-500 mb-1">
              {t('taskDetails.evidence.claimedFiles', { defaultValue: 'Files the agent claims to have written' })}
            </p>
            {claimedFiles.length > 0 ? (
              <ul className="space-y-0.5">
                {claimedFiles.map(file => (
                  <li key={file} className="font-mono text-xs text-gray-300 break-all">
                    {capabilities?.memory
                      ? <Link to={lineagePath(file)} className="hover:text-brand-300 hover:underline"
                          title={t('lineage.open', { defaultValue: 'See the decisions recorded on this file' })}>{file}</Link>
                      : file}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-500">{t('taskDetails.evidence.noFiles', { defaultValue: 'No files claimed.' })}</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

export default function TaskDetails() {
  const { t } = useTranslation()
  const { taskId, sprintId: paramSprintId } = useParams<{ taskId: string; sprintId: string }>()
  const { activeSprintId, companyId } = useAppStore()
  // Keep the lookup context visible if a 404 clears the persisted selection.
  const [lookup] = useState({ sprintId: activeSprintId, companyId })

  const parsedTaskId = parseRouteId(taskId)
  const resolvedSprintId = paramSprintId ? parseRouteId(paramSprintId)
    : activeSprintId ?? (companyId === lookup.companyId ? lookup.sprintId : null)
  const { data: board, isLoading, isError, error, refetch } = useSprintBoard(parsedTaskId === null ? null : resolvedSprintId)

  const task: BacklogItem | undefined = board
    ? Object.values(board.columns).flat().find(item => item.id === parsedTaskId)
    : undefined

  const sprintsLabel = t('nav.sprints', { defaultValue: 'Sprints' })
  const backTo = resolvedSprintId ? `/sprints/${resolvedSprintId}/board` : '/sprints'

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto py-8 px-4 space-y-5">
        <SkeletonLine className="w-32 h-4" />
        <SkeletonBlock className="h-8 w-3/4" />
        <SkeletonBlock className="h-24" />
        <div className="grid grid-cols-2 gap-4">
          <SkeletonBlock className="h-12" />
          <SkeletonBlock className="h-12" />
        </div>
      </div>
    )
  }

  if (parsedTaskId === null || resolvedSprintId === null || isError || !task) {
    const sprintNotFound = error instanceof ApiError && error.status === 404
    const message = parsedTaskId === null ? 'taskDetails.invalidId'
      : paramSprintId && resolvedSprintId === null ? 'workspace.invalidId'
      : resolvedSprintId === null ? 'taskDetails.noSprint'
      : isError ? sprintNotFound ? 'taskDetails.sprintNotFound' : 'taskDetails.loadError'
      : 'taskDetails.notFound'
    return (
      <div className="max-w-2xl mx-auto py-16 px-4 text-center">
        <p role="alert" className="text-gray-400 mb-4">{t(message, { id: paramSprintId, taskId, sprintId: resolvedSprintId })}</p>
        {parsedTaskId !== null && resolvedSprintId !== null && isError && !sprintNotFound && (
          <button onClick={() => refetch()} className="btn btn-ghost text-sm mr-3">{t('common.retry')}</button>
        )}
        <Link to={sprintNotFound ? '/sprints' : backTo} className="btn btn-ghost text-sm">
          <ArrowLeft size={14} className="mr-1" /> {t('common.back')}
        </Link>
      </div>
    )
  }

  const lineage = carryOverLineage(task.comments)

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <div className="mb-6">
        <Breadcrumbs items={[
          { label: sprintsLabel, to: '/sprints' },
          {
            label: board?.sprint?.sprint_name || t('workspace.sprintLabel', { id: resolvedSprintId, defaultValue: 'Sprint #{{id}}' }),
            to: backTo,
          },
          { label: task.title },
        ]} />
      </div>

      {/* Header */}
      <div className="mb-6">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <span className={`px-2 py-0.5 rounded-md border text-xs font-semibold uppercase tracking-wide ${STATUS_STYLES[task.status]}`}>
            {t(`kanban.status.${task.status}`, task.status)}
          </span>
          <span className={`px-2 py-0.5 rounded-md border text-xs font-medium ${PRIORITY_STYLES[task.priority]}`}>
            <Flag size={10} className="inline mr-1" />
            {t(`kanban.${task.priority}`, task.priority)}
          </span>
        </div>
        <h1 className="text-xl font-bold text-white leading-snug">{task.title}</h1>
      </div>

      {/* Carry-over lineage: another attempt at an earlier task, or the attempt this one got */}
      {(lineage.from || lineage.to) && (
        <nav aria-label={t('taskDetails.lineageLabel', { defaultValue: 'Earlier and later attempts' })} className="card p-3 mb-4 space-y-1 text-xs text-gray-400">
          {lineage.from && (
            <p>
              <RotateCcw size={11} className="inline mr-1" aria-hidden="true" />
              {t('taskDetails.carriedFrom', { sprint: lineage.from.sprintName, defaultValue: 'Another attempt at a task blocked in {{sprint}}:' })}{' '}
              <Link to={`/task/${lineage.from.taskId}`} className="text-brand-300 hover:underline">
                {t('taskDetails.taskNumber', { id: lineage.from.taskId, defaultValue: 'task #{{id}}' })}
              </Link>
            </p>
          )}
          {lineage.to && (
            <p>
              <RotateCcw size={11} className="inline mr-1" aria-hidden="true" />
              {t('taskDetails.carriedTo', { sprint: lineage.to.sprintName, defaultValue: 'Given another attempt in {{sprint}}:' })}{' '}
              <Link to={`/sprints/${lineage.to.sprintId}/tasks/${lineage.to.taskId}`} className="text-brand-300 hover:underline">
                {t('taskDetails.taskNumber', { id: lineage.to.taskId, defaultValue: 'task #{{id}}' })}
              </Link>
            </p>
          )}
        </nav>
      )}

      {/* Description */}
      {task.description && (
        <div className="card p-4 mb-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-2">{t('generate.story')}</p>
          <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">{task.description}</p>
        </div>
      )}

      {/* Meta */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="card p-3">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
            <User size={10} /> {t('kanban.assignee')}
          </p>
          <p className="text-sm text-gray-200">{task.assignee || t('common.na')}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-1 flex items-center gap-1">
            <Clock size={10} /> {t('support.updated')}
          </p>
          <p className="text-sm text-gray-200">{formatDate(task.updated_at)}</p>
        </div>
      </div>

      {companyId !== null && <TaskEvidence companyId={companyId} taskId={task.id} />}

      {companyId !== null && (
        <div className="card p-4 mb-4">
          <Conversation companyId={companyId} taskId={task.id} />
        </div>
      )}

      {/* Comments */}
      {task.comments.length > 0 && (
        <div className="card p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-semibold mb-3 flex items-center gap-1">
            <MessageSquare size={10} /> {t('support.timeline')} ({task.comments.length})
          </p>
          <div className="space-y-3">
            {task.comments.map((c, i) => (
              <div key={i} className="flex gap-3 text-sm">
                <div className="w-6 h-6 rounded-full bg-brand-600/30 border border-brand-600/40 flex items-center justify-center text-[10px] font-bold text-brand-300 shrink-0 mt-0.5">
                  {c.author.slice(0, 1).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-medium text-gray-300">{c.author}</span>
                    <span className="text-[11px] text-gray-600">{formatDate(c.created_at)}</span>
                  </div>
                  <p className="text-gray-400 text-xs leading-relaxed">{c.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
