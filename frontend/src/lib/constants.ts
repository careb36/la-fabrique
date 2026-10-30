// ─── localStorage keys ────────────────────────────────────────────────────────
export const STORAGE_KEY_APP   = 'fabrique-app-storage'
export const STORAGE_KEY_LANG  = 'fabrique-lang'
export const STORAGE_KEY_EMAIL = 'fabrique-support-email'

// ─── SSE / reconnect ──────────────────────────────────────────────────────────
export const SSE_RECONNECT_DELAY_MS     = 3_000
export const SSE_MAX_RECONNECT_DELAY_MS = 30_000
export const SSE_MAX_RECONNECT_ATTEMPTS = 10
export const SSE_KEEPALIVE_INTERVAL_MS  = 15_000

// ─── GlassRoom ────────────────────────────────────────────────────────────────
export const AGENT_ACTIVE_TTL_MS   = 90_000   // how long an agent stays "active" with no new event
export const MAX_MESSAGES          = 500       // cap on in-memory SSE messages
export const COPY_FEEDBACK_MS      = 1_500     // how long "Copied!" stays visible
export const SSE_REPLAY_BUFFER     = 50        // backend replays last N events on connect

// ─── Sprint scope ─────────────────────────────────────────────────────────────
export const SCOPE_LIMITS: Record<string, number> = { S: 4, M: 8, L: 12 }
export const SCOPE_DAYS:   Record<string, number> = { S: 7, M: 14, L: 21 }
export const DEFAULT_SCOPE = 'M'

// ─── Agent token budgets ──────────────────────────────────────────────────────
export const DEFAULT_AGENT_TOKEN_BUDGET = 500_000

// ─── Models ───────────────────────────────────────────────────────────────────
export const DEFAULT_MODEL = 'gemini-pro'
