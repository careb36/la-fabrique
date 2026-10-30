import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { WorkspacePlatform } from '../services/api'
import { DAEMON_START_COMMANDS, daemonCommandKinds } from '../lib/workspace'

/**
 * Explains that the native workspace daemon is not connected and how to start
 * it: the command for the given platform, or both when it is not known.
 */
export function WorkspaceDaemonHelp({ platform, detail, children, role = 'alert' }: {
  platform?: WorkspacePlatform | null
  /** `alert` after a failed request; `status` for the passive connection indicator. */
  role?: 'alert' | 'status'
  /** The server's own explanation, when it gave one. */
  detail?: string
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const kinds = daemonCommandKinds(platform)
  return (
    <div role={role} className="rounded-lg border border-yellow-800/60 bg-yellow-900/20 p-3 text-xs text-yellow-200 space-y-2">
      <p className="font-semibold">{t('workspaceDaemon.notConnected')}</p>
      {detail && <p className="text-yellow-300/80">{detail}</p>}
      <p>{t('workspaceDaemon.startHint')}</p>
      <ul className="space-y-1.5">
        {kinds.map(kind => (
          <li key={kind} className="min-w-0">
            <span className="block text-yellow-300/80">
              {kind === 'windows' ? t('workspaceDaemon.windowsLabel') : t('workspaceDaemon.unixLabel')}
            </span>
            <code className="block break-all rounded bg-surface-900/80 px-2 py-1 font-mono text-gray-100">
              {DAEMON_START_COMMANDS[kind]}
            </code>
          </li>
        ))}
      </ul>
      {children}
    </div>
  )
}
