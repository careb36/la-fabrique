import type { WorkspacePlatform } from '../services/api'

/** Commands that start the native workspace daemon, per host family. */
export const DAEMON_START_COMMANDS = {
  unix: './scripts/start-daemon.sh',
  windows: '.\\scripts\\start-daemon.ps1',
} as const

export type DaemonCommandKind = keyof typeof DAEMON_START_COMMANDS

/**
 * Which start command(s) to show: the one for the reported platform, or both
 * when the platform is not known.
 */
export function daemonCommandKinds(platform?: WorkspacePlatform | null): DaemonCommandKind[] {
  if (platform === 'win32') return ['windows']
  if (platform === 'darwin' || platform === 'linux') return ['unix']
  return ['unix', 'windows']
}

/**
 * Best guess of the user's own OS before the daemon reports one: the desktop
 * app knows it exactly, a browser only through its user agent.
 */
export function clientPlatform(): WorkspacePlatform | undefined {
  if (typeof window === 'undefined') return undefined
  const electronPlatform = window.electronAPI?.platform
  if (electronPlatform) return electronPlatform
  const agent = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/Windows/i.test(agent)) return 'win32'
  if (/Macintosh|Mac OS X/i.test(agent)) return 'darwin'
  if (/Linux|X11/i.test(agent)) return 'linux'
  return undefined
}
