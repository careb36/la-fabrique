import { app, BrowserWindow, Menu, dialog, shell } from 'electron'
import * as path from 'path'
import { isWebUrl, setupIpcHandlers } from './ipc-handlers'

// `npm run electron:dev` passes --dev and serves the renderer from Vite;
// otherwise the built renderer is loaded from dist/.
const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development'
const DEV_SERVER_URL = process.env.ELECTRON_DEV_URL || 'http://localhost:5173'

let mainWindow: BrowserWindow | null = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      // Compiled next to this file (dist-electron-main/preload.js).
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    title: 'Fabrique'
  })

  // Links with target="_blank" (e.g. a repository's GitHub page) open in the
  // user's browser instead of a new Electron window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isWebUrl(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })

  if (isDev) {
    // The Vite dev server may still be starting when Electron comes up.
    mainWindow.webContents.on('did-fail-load', (_event, _code, _description, url) => {
      if (url.startsWith(DEV_SERVER_URL)) setTimeout(() => mainWindow?.loadURL(DEV_SERVER_URL), 1000)
    })
    mainWindow.loadURL(DEV_SERVER_URL)
    mainWindow.webContents.openDevTools()
  } else {
    // Relative to dist-electron-main/: the renderer build lives in dist/.
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function navigate(route: string) {
  mainWindow?.webContents.send('navigate', route)
}

function createMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' as const }] : []),
    {
      label: 'File',
      submenu: [
        process.platform === 'darwin' ? { role: 'close' } : { role: 'quit' }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Factory',
      submenu: [
        {
          label: 'Evidence',
          click: () => navigate('/evidence')
        },
        {
          label: 'Sprints',
          click: () => navigate('/sprints')
        },
        {
          label: 'New Company',
          click: () => navigate('/companies/new')
        }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'About Fabrique',
          click: () => {
            void dialog.showMessageBox({
              type: 'info',
              title: 'About Fabrique',
              message: `Fabrique v${app.getVersion()}`,
              detail: 'Factory system with LangGraph orchestration'
            })
          }
        }
      ]
    }
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

app.whenReady().then(() => {
  setupIpcHandlers()
  createWindow()
  createMenu()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
