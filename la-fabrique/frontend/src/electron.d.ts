/**
 * The API the Electron preload script (`electron/preload.ts`) exposes on
 * `window.electronAPI`. Only present in the desktop app; in a browser
 * `window.electronAPI` is undefined.
 */
export interface ElectronAPI {
  /** Node platform of the machine running the desktop app (`darwin`, `linux`, `win32`, …). */
  platform: string
  versions: {
    node: string
    chrome: string
    electron: string
  }
  /** Opens the native folder dialog; resolves to the chosen absolute path, or null when cancelled. */
  selectDirectory(): Promise<string | null>
  /** Subscribes to navigation requests from the application menu; returns an unsubscribe function. */
  onNavigate(callback: (path: string) => void): () => void
  getBackendUrl(): Promise<string>
  getAppVersion(): Promise<string>
  /** Opens an http(s) URL in the user's default browser. */
  openExternal(url: string): Promise<void>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
