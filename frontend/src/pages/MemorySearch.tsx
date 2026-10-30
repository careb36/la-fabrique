import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorDetail, type MemoryResult } from '../services/api'
import { useSearchMemory, useStoreMemory } from '../hooks/useQueries'
import { Search, Loader2, Database, ChevronDown, ChevronUp, Save } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

// The API takes the note as a query parameter, so long text is capped.
const MAX_NOTE_LENGTH = 2000

function MetadataView({ metadata }: { metadata: unknown }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  if (!metadata) return null

  let text: string
  try {
    text = typeof metadata === 'string' ? metadata : JSON.stringify(metadata, null, 2)
  } catch {
    text = String(metadata)
  }

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {t('memorySearch.metadata', { defaultValue: 'metadata' })}
      </button>
      {open && (
        <pre className="mt-1 text-xs text-gray-400 bg-surface-900 border border-surface-700 p-2 rounded overflow-auto max-h-40 font-mono">
          {text}
        </pre>
      )}
    </div>
  )
}

export default function MemorySearch() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(10)
  const [submitted, setSubmitted] = useState<{ query: string; limit: number } | null>(null)
  const search = useSearchMemory(submitted?.query ?? '', companyId, submitted?.limit ?? limit)
  const results: MemoryResult[] = search.data?.results ?? []

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setSubmitted({ query: query.trim(), limit })
  }

  function scoreClass(s: number) {
    if (s >= 0.85) return 'text-status-success'
    if (s >= 0.65) return 'text-yellow-400'
    return 'text-gray-500'
  }

  return (
    <div className="page-container max-w-4xl">
      <div className="page-header mb-6">
        <div className="flex items-center gap-2">
          <Database className="text-brand-400" size={22} />
          <h1 className="page-title">{t('memorySearch.title')}</h1>
        </div>
        <p className="text-gray-400 mt-1">{t('memorySearch.subtitle')}</p>
      </div>

      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={t('memorySearch.queryPlaceholder')}
            aria-label={t('memorySearch.queryPlaceholder')}
            className="input flex-1"
          />
          <input
            type="number"
            value={limit}
            onChange={e => setLimit(parseInt(e.target.value) || 10)}
            min={1} max={100}
            className="input w-24 flex-shrink-0"
            title={t('memorySearch.limit')}
            aria-label={t('memorySearch.limit')}
          />
          <button
            type="submit"
            disabled={search.isFetching || !query.trim()}
            className="btn btn-primary flex-shrink-0"
          >
            {search.isFetching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
            {search.isFetching ? t('memorySearch.searching') : t('memorySearch.search')}
          </button>
        </div>
      </form>

      {search.isError && (
        <div role="alert" className="alert-error mb-4 flex flex-wrap items-center gap-2">
          <span>{t('memorySearch.errorDetail', { message: errorDetail(search.error), defaultValue: 'Search failed: {{message}}' })}</span>
          <button type="button" onClick={() => void search.refetch()} className="underline">{t('common.retry')}</button>
        </div>
      )}

      {!submitted && (
        <div className="empty-state py-16">
          <Database size={32} className="mx-auto mb-3 text-gray-600" />
          <p className="text-gray-500">{t('memorySearch.query', 'Enter a query to search memory')}</p>
        </div>
      )}

      {search.isFetching && (
        <div className="space-y-3">
          {[1,2,3].map(i => <div key={i} className="skeleton h-20 rounded-lg" />)}
        </div>
      )}

      {submitted && search.isSuccess && !search.isFetching && (
        <>
          <p className="text-sm text-gray-500 mb-4">
            {results.length === 0
              ? t('memorySearch.noResults')
              : t('memorySearch.resultCount', { count: results.length, defaultValue: '{{count}} results' })}
          </p>
          <div className="space-y-3">
            {results.map((r, i) => (
              <div key={i} className="card p-4">
                <div className="flex items-start justify-between gap-3 mb-2">
                  <span className="text-xs text-gray-500">#{i + 1}</span>
                  <span className={`text-xs font-semibold font-mono ${scoreClass(r.similarity)}`}>
                    {(r.similarity * 100).toFixed(1)}%
                  </span>
                </div>
                <p className="text-gray-200 text-sm leading-relaxed">{r.content}</p>
                <MetadataView metadata={r.metadata} />
              </div>
            ))}
          </div>
        </>
      )}

      <StoreMemoryForm companyId={companyId} />
    </div>
  )
}

/** Adds a note to the company's memory (`POST /v1/memory/store`, Manager). */
function StoreMemoryForm({ companyId }: { companyId: number | null }) {
  const { t } = useTranslation()
  const store = useStoreMemory()
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(false)

  function save() {
    const content = note.trim()
    if (!content) return
    setSaved(false)
    store.mutate(
      { content, companyId, metadata: { source: 'memory_page' } },
      { onSuccess: () => { setNote(''); setSaved(true) } },
    )
  }

  return (
    <section aria-labelledby="store-memory-title" className="card p-4 mt-8">
      <h2 id="store-memory-title" className="text-sm font-semibold text-white">
        {t('memorySearch.storeTitle', { defaultValue: 'Add to memory' })}
      </h2>
      <p className="text-xs text-gray-500 mt-1 mb-3">
        {t('memorySearch.storeHint', { defaultValue: 'Agents retrieve these notes as context for the company\'s tasks.' })}
      </p>
      <form onSubmit={e => { e.preventDefault(); save() }} className="space-y-2">
        <textarea
          value={note}
          onChange={e => { setNote(e.target.value); setSaved(false) }}
          maxLength={MAX_NOTE_LENGTH}
          rows={3}
          aria-label={t('memorySearch.storeLabel', { defaultValue: 'Note to remember' })}
          placeholder={t('memorySearch.storePlaceholder', { defaultValue: 'A decision, a convention or a fact the agents should know' })}
          className="input w-full"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={store.isPending || !note.trim()} className="btn btn-secondary btn-sm">
            {store.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {store.isPending
              ? t('memorySearch.storing', { defaultValue: 'Saving…' })
              : t('memorySearch.store', { defaultValue: 'Save to memory' })}
          </button>
          <span className="text-xs text-gray-600">{note.length}/{MAX_NOTE_LENGTH}</span>
          {saved && (
            <span role="status" className="text-xs text-status-success">
              {t('memorySearch.stored', { defaultValue: 'Saved to memory' })}
            </span>
          )}
        </div>
        {store.isError && (
          <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
            <span>{t('memorySearch.storeError', { message: errorDetail(store.error), defaultValue: 'Could not save: {{message}}' })}</span>
            <button type="button" onClick={save} className="underline">{t('common.retry')}</button>
          </div>
        )}
      </form>
    </section>
  )
}
