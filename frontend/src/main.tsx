import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './lib/queryClient'
import App from './App'
import { useAuthStore } from './store/useAuthStore'
import './styles/index.css'
import './i18n'

/**
 * Session handoff from the desktop launcher.
 *
 * The launcher trades its operator key for a session and opens
 * `/#sesion=<token>&caduca=<seconds>`. The fragment never reaches the server
 * (so it cannot land in an access log), and it is scrubbed from the address
 * bar as soon as it is adopted, so a reload or a shared link never carries it.
 */
function adoptHandoffSession(): void {
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash.includes('sesion=')) return
  const params = new URLSearchParams(hash)
  const token = params.get('sesion')
  if (!token) return
  const seconds = Number(params.get('caduca')) || 3600
  // Never replace a session already open in this browser: a link from
  // anywhere could otherwise swap the person into someone else's account.
  if (!useAuthStore.getState().getValidToken()) {
    useAuthStore.getState().adoptSession(token, seconds)
  }
  window.history.replaceState({}, '', window.location.pathname + window.location.search)
}

adoptHandoffSession()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
)
