import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { GitBranch, Loader2, Search } from 'lucide-react'
import { useCapabilities, useLineage } from '../hooks/useQueries'
import { errorDetail } from '../services/api'
import { useAppStore } from '../store/useAppStore'

/** Link target for the decisions recorded on a file. */
export function lineagePath(filePath: string): string {
  return `/lineage?${new URLSearchParams({ file: filePath })}`
}

/**
 * File lineage: the agent decisions recorded on a file in the knowledge graph
 * (`GET /v1/enterprise/lineage`). The file comes from the `file` query
 * parameter, so a claimed file links straight here.
 */
export default function Lineage() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const { data: capabilities } = useCapabilities()
  const [params, setParams] = useSearchParams()
  const file = params.get('file') ?? ''
  const [draft, setDraft] = useState(file)
  const lineage = useLineage(file, companyId)
  const entries = lineage.data?.lineage ?? []

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const value = draft.trim()
    if (value) setParams({ file: value })
  }

  return (
    <div className="page-container max-w-3xl">
      <div className="page-header mb-6">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="text-brand-400" size={22} />
            <h1 className="page-title">{t('lineage.title', { defaultValue: 'File lineage' })}</h1>
          </div>
          <p className="text-gray-400 mt-1">
            {t('lineage.subtitle', { defaultValue: 'The agent decisions recorded on a file, newest first (up to 10).' })}
          </p>
        </div>
      </div>

      {capabilities && !capabilities.memory && (
        <p role="status" className="mb-4 text-sm text-amber-300">
          {t('lineage.unavailable', { defaultValue: 'Lineage needs the knowledge graph (Neo4j), which is not connected.' })}
        </p>
      )}

      <form onSubmit={submit} className="mb-6 flex gap-2">
        <label className="flex-1">
          <span className="sr-only">{t('lineage.file', { defaultValue: 'File path' })}</span>
          <input value={draft} onChange={e => setDraft(e.target.value)} className="input w-full font-mono text-sm"
            placeholder={t('lineage.filePlaceholder', { defaultValue: 'src/app/main.py' })} />
        </label>
        <button type="submit" disabled={!draft.trim()} className="btn btn-primary">
          <Search size={15} /> {t('lineage.search', { defaultValue: 'Show' })}
        </button>
      </form>

      {!file ? null : lineage.isLoading ? (
        <div role="status" className="flex items-center gap-2 text-sm text-gray-400">
          <Loader2 size={15} className="animate-spin" /> {t('lineage.loading', { defaultValue: 'Loading decisions…' })}
        </div>
      ) : lineage.isError ? (
        <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
          <span>{t('lineage.error', { message: errorDetail(lineage.error), defaultValue: 'Could not load the lineage: {{message}}' })}</span>
          <button type="button" onClick={() => lineage.refetch()} className="underline">{t('common.retry')}</button>
        </div>
      ) : entries.length === 0 ? (
        <p className="text-sm text-gray-400">
          {t('lineage.empty', { file, defaultValue: 'No decisions recorded for {{file}}.' })}
        </p>
      ) : (
        <ol className="space-y-3" aria-label={t('lineage.listLabel', { file, defaultValue: 'Decisions on {{file}}' })}>
          {entries.map(entry => (
            <li key={entry.engram_id} className="card p-4">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                <span className="badge">{entry.role ?? t('lineage.unknownRole', { defaultValue: 'unknown role' })}</span>
                {entry.timestamp && <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleString()}</time>}
                {entry.legacy && (
                  <span className="text-amber-300" title={t('lineage.legacyHint', { defaultValue: 'Recorded before decisions carried a company.' })}>
                    {t('lineage.legacy', { defaultValue: 'no company' })}
                  </span>
                )}
              </div>
              <p className="whitespace-pre-wrap break-words text-sm text-gray-200">
                {entry.decision || t('lineage.noSummary', { defaultValue: 'No summary recorded.' })}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
