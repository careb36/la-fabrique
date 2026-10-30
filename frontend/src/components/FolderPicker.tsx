import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  api,
  ApiError,
  errorDetail,
  type WorkspaceBrowseResponse,
  type WorkspacePlatform,
} from '../services/api'
import { WorkspaceDaemonHelp } from './WorkspaceDaemonHelp'

interface BrowseError {
  status: number
  message: string
}

/**
 * Browses folders on the user's own computer through the workspace daemon
 * (`GET /v1/workspace/browse`) and returns the chosen absolute path.
 *
 * Paths are host-native and opaque: every navigation uses a `path` the API
 * returned (an entry, `parent`, a shortcut or a root), never a joined string.
 */
export function FolderPicker({ initialPath, platform, onSelect, onClose }: {
  /** Folder to open first; the home folder when omitted. */
  initialPath?: string
  /** Host platform if already known (e.g. from the daemon status), for the start-command help. */
  platform?: WorkspacePlatform | null
  onSelect: (path: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const requestRef = useRef(0)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const [listing, setListing] = useState<WorkspaceBrowseResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<BrowseError | null>(null)
  const [lastRequested, setLastRequested] = useState<string | undefined>(initialPath)

  const load = useCallback(async (path?: string) => {
    const request = ++requestRef.current
    setLoading(true)
    setError(null)
    setLastRequested(path)
    try {
      const response = await api.browseWorkspace(path)
      if (request !== requestRef.current) return
      setListing(response)
    } catch (err) {
      if (request !== requestRef.current) return
      setError({ status: err instanceof ApiError ? err.status : 0, message: errorDetail(err) })
    } finally {
      if (request === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(initialPath || undefined)
    return () => { requestRef.current++ }
  }, [load, initialPath])

  useEffect(() => {
    dialogRef.current?.focus()
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [])

  // Entering a folder replaces the button that had focus; keep keyboard users
  // inside the dialog instead of dropping them on <body>.
  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.contains(document.activeElement)) dialog.focus()
  }, [listing, error])

  const hostPlatform = listing?.host.platform ?? platform
  const showListing = listing !== null && error === null

  return (
    <div className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center bg-black/60 p-0 sm:p-4"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="flex w-full max-w-xl max-h-[90vh] flex-col overflow-hidden rounded-t-xl sm:rounded-xl border border-surface-700 bg-surface-900 shadow-xl focus:outline-none">
        {/* Header */}
        <div className="flex items-start justify-between gap-2 border-b border-surface-700 px-4 py-3">
          <div className="min-w-0">
            <h2 id={titleId} className="text-sm font-semibold text-white">{t('folderPicker.title')}</h2>
            {listing && (
              <p className="text-xs text-gray-500 truncate">
                {t('folderPicker.hostLine', {
                  hostname: listing.host.hostname,
                  platform: t(`workspaceDaemon.platforms.${listing.host.platform}`, { defaultValue: listing.host.platform }),
                })}
              </p>
            )}
          </div>
          <button type="button" onClick={onClose} aria-label={t('common.close')}
            className="btn-ghost btn-icon flex-shrink-0 text-lg leading-none">×</button>
        </div>

        {/* Current path + Up */}
        {listing && (
          <div className="flex items-center gap-2 border-b border-surface-700 px-4 py-2">
            {listing.parent !== null && (
              <button type="button" disabled={loading}
                onClick={() => void load(listing.parent!)}
                aria-label={t('folderPicker.upLabel')} title={t('folderPicker.upLabel')}
                className="btn-secondary btn-sm flex-shrink-0">
                ↑ {t('folderPicker.up')}
              </button>
            )}
            <p className="min-w-0 flex-1 break-all font-mono text-xs text-gray-200">
              <span className="sr-only">{t('folderPicker.currentFolder')}: </span>
              <span data-testid="folder-picker-path">{listing.path}</span>
            </p>
          </div>
        )}

        {/* Shortcuts and roots */}
        {listing && (listing.shortcuts.length > 0 || listing.roots.length > 1) && (
          <div className="space-y-2 border-b border-surface-700 px-4 py-2">
            {listing.shortcuts.length > 0 && (
              <div role="group" aria-label={t('folderPicker.shortcuts')} className="flex flex-wrap gap-1.5">
                {listing.shortcuts.map(shortcut => (
                  <button key={shortcut.path} type="button" disabled={loading} title={shortcut.path}
                    onClick={() => void load(shortcut.path)}
                    className={`badge border ${shortcut.path === listing.path ? 'border-brand-500 bg-brand-900/40 text-brand-200' : 'border-surface-600 bg-surface-800 text-gray-300 hover:bg-surface-700'}`}>
                    {shortcut.name}
                  </button>
                ))}
              </div>
            )}
            {listing.roots.length > 1 && (
              <div role="group" aria-label={t('folderPicker.roots')} className="flex flex-wrap gap-1.5">
                {listing.roots.map(root => (
                  <button key={root.path} type="button" disabled={loading} title={root.path}
                    onClick={() => void load(root.path)}
                    className="badge border border-surface-600 bg-surface-800 font-mono text-gray-300 hover:bg-surface-700">
                    {root.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Body */}
        <div className="min-h-[8rem] flex-1 overflow-y-auto px-2 py-2">
          {loading && (
            <p role="status" className="flex items-center gap-2 px-2 py-3 text-sm text-gray-400">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              {t('folderPicker.loading')}
            </p>
          )}

          {!loading && error?.status === 503 && (
            <WorkspaceDaemonHelp platform={hostPlatform} detail={error.message}>
              <button type="button" onClick={() => void load(lastRequested)} className="btn-secondary btn-sm">
                {t('common.retry')}
              </button>
            </WorkspaceDaemonHelp>
          )}

          {!loading && error && error.status !== 503 && (
            <div role="alert" className="alert-error flex-col items-start text-sm">
              <span>{t('folderPicker.error', { message: error.message })}</span>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => void load(lastRequested)} className="btn-secondary btn-sm">
                  {t('common.retry')}
                </button>
                {lastRequested !== undefined && (
                  <button type="button" onClick={() => void load()} className="btn-secondary btn-sm">
                    {t('folderPicker.home')}
                  </button>
                )}
              </div>
            </div>
          )}

          {!loading && showListing && listing.entries.length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-gray-500">{t('folderPicker.empty')}</p>
          )}

          {!loading && showListing && listing.entries.length > 0 && (
            <ul aria-label={t('folderPicker.folders')} className="space-y-0.5">
              {listing.entries.map(entry => (
                <li key={entry.path}>
                  <button type="button" onClick={() => void load(entry.path)} title={entry.path}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-gray-200 hover:bg-surface-800 focus-visible:bg-surface-800 focus-visible:outline-none">
                    <span aria-hidden="true">📁</span>
                    <span className="min-w-0 flex-1 truncate font-mono">{entry.name}</span>
                    {entry.is_git && (
                      <span className="badge flex-shrink-0 bg-green-900/50 text-green-300 ring-1 ring-green-700/50"
                        title={t('folderPicker.gitBadgeTitle')}>
                        {t('folderPicker.gitBadge')}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {!loading && showListing && listing.truncated && (
            <p className="px-2 pt-2 text-xs text-gray-500">{t('folderPicker.truncated')}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-col-reverse gap-2 border-t border-surface-700 px-4 py-3 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className="btn-secondary">{t('common.cancel')}</button>
          <button type="button" disabled={loading || !showListing}
            onClick={() => listing && onSelect(listing.path)}
            className="btn-primary">
            {t('folderPicker.useThis')}
          </button>
        </div>
      </div>
    </div>
  )
}
