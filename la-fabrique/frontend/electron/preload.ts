import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import type { ElectronAPI } from '../src/electron'

const electronAPI: ElectronAPI = {
  platform: process.platform,
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron,
  },
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  onNavigate: callback => {
    const listener = (_event: IpcRendererEvent, path: unknown) => {
      if (typeof path === 'string') callback(path)
    }
    ipcRenderer.on('navigate', listener)
    return () => {
      ipcRenderer.removeListener('navigate', listener)
    }
  },
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  openExternal: url => ipcRenderer.invoke('open-external', url),
}

contextBridge.exposeInMainWorld('electronAPI', electronAPI)
