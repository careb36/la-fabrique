import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'

/** Opens only web links in the user's browser, never file:// or custom schemes. */
export function isWebUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url)
    return protocol === 'https:' || protocol === 'http:'
  } catch {
    return false
  }
}

export function setupIpcHandlers() {
  ipcMain.handle('get-backend-url', () => {
    return process.env.BACKEND_URL || 'http://localhost:8000'
  })

  ipcMain.handle('open-external', async (_event, url: unknown) => {
    if (typeof url !== 'string' || !isWebUrl(url)) throw new Error('Only http(s) URLs can be opened')
    await shell.openExternal(url)
  })

  ipcMain.handle('get-app-version', () => {
    return app.getVersion()
  })

  // Native folder dialog for choosing the project folder; resolves to the
  // chosen absolute path, or null when the user cancels.
  ipcMain.handle('select-directory', async event => {
    const options: Electron.OpenDialogOptions = { properties: ['openDirectory'] }
    const window = BrowserWindow.fromWebContents(event.sender)
    const result = window
      ? await dialog.showOpenDialog(window, options)
      : await dialog.showOpenDialog(options)
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })
}
