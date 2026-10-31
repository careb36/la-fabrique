import { API_BASE } from './apiBase'
import { useAuthStore } from '../store/useAuthStore'

/**
 * Session handoff from the desktop launcher.
 *
 * The launcher opens `/#codigo=<code>`: a single-use code that expires within
 * a minute, never a session token. A URL lands on the browser's command line
 * and in its history; by the time anyone could read the code there it is
 * spent. The page trades it for the session with a POST, scrubs it from the
 * address bar, and never replaces a session already open in this browser, so
 * a link from anywhere cannot swap the person into another account.
 */
export async function adoptHandoff(fetchImpl: typeof fetch = fetch): Promise<void> {
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash.includes('codigo=')) return
  const code = new URLSearchParams(hash).get('codigo')
  window.history.replaceState({}, '', window.location.pathname + window.location.search)
  if (!code || useAuthStore.getState().getValidToken()) return
  try {
    const response = await fetchImpl(`${API_BASE}/v1/auth/desktop/redeem`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    })
    if (!response.ok) return
    const body = (await response.json()) as { access_token?: string; expires_in?: number }
    if (body.access_token) {
      useAuthStore.getState().adoptSession(body.access_token, Number(body.expires_in) || 3600)
    }
  } catch {
    // No session: the login screen is the fallback.
  }
}
