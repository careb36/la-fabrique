/**
 * Where the API lives.
 *
 * The bundled product serves this app *and* `/v1` from one process, so the
 * default is same-origin and the port never has to be configured. The dev
 * server proxies `/v1` to the backend, `VITE_API_URL` still wins when the UI
 * is hosted separately, and the Electron build (`file://`) falls back to
 * localhost because a file URL has no useful origin.
 */
function sameOrigin(): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return origin && !origin.startsWith('file:') ? origin : 'http://localhost:8000'
}

export const API_BASE = import.meta.env.VITE_API_URL || sameOrigin()
