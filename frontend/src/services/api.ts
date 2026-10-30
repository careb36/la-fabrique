import { API_BASE } from '../lib/apiBase'
import { useAuthStore } from '../store/useAuthStore'

const TIMEOUT_MS = 90_000
const MAX_RETRIES = 2

// ── Error types ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  /** The server's own `detail` message, when the error body carried one. */
  public detail?: string

  constructor(public status: number, message: string, detail?: string) {
    super(message)
    this.name = 'ApiError'
    this.detail = detail
  }
}

/** The server's `detail` when present, else the generic message. */
export function errorDetail(error: unknown): string {
  if (error instanceof ApiError) return error.detail || error.message
  return error instanceof Error ? error.message : String(error)
}

export function isClientError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status >= 400 && error.status < 500
}

function friendlyMessage(status: number): string {
  const map: Record<number, string> = {
    400: 'Invalid request. Please check the form and try again.',
    401: 'Session expired. Please refresh the page.',
    403: 'You do not have permission for this action.',
    404: 'Resource not found.',
    422: 'Invalid data submitted. Please review your inputs.',
    429: 'Too many requests. Please wait a moment and retry.',
    500: 'Server error. Our team has been notified.',
    502: 'Service temporarily unavailable.',
    503: 'Service is starting up. Try again in a few seconds.',
  }
  return map[status] ?? `Unexpected error (${status}). Please try again.`
}

// ── Interfaces ───────────────────────────────────────────────────────────────

export interface CompanyInfo {
  id: number
  name: string
  autonomy_level: number
  token_quota: number
  token_used: number
}

export interface Capabilities {
  agent_graph: boolean
  memory: boolean
  github: boolean
  auth_required: boolean
  /** The Support agent triages new tickets (SUPPORT_AGENT_ENABLED). */
  support_agent?: boolean
  /** Where GitHub can reach the backend (PUBLIC_API_URL); null when unset. */
  public_api_url?: string | null
}

export type ComponentStatus = { status: 'up' | 'down'; reason?: string; detail?: string }

export interface DeepHealth {
  status: 'healthy' | 'degraded' | 'down'
  components: Record<string, ComponentStatus>
  nats?: string
}

export interface InitCompanyRequest {
  company_name: string
  description?: string
  default_scope_size?: 'S' | 'M' | 'L'
  default_sprint_length_days?: number
  autonomy_level?: number
  timezone?: string
  agents?: DiscoverTeamAgent[]
  permissions?: Record<string, string>
  governance?: Record<string, boolean>
  project_path?: string
  detected_stack?: DetectedStack
}

export interface InitCompanyResponse {
  company_id: number
  sprint_id: number
  task_count: number
  message: string
}

export interface AuthUser {
  user_id: number
  email: string
  full_name: string
  /** Listed in the backend's SUPPORT_ADMIN_EMAILS: triages every ticket. */
  support_admin?: boolean
}

export interface CompanyMembership {
  company_id: number
  human_role: 'Owner' | 'Manager' | 'Viewer'
}

export interface AuthProfile extends AuthUser {
  memberships: CompanyMembership[]
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface RegisterResponse {
  user_id: number
  email: string
}

export interface DetectedStack {
  name: string
  language: string
  all_languages?: Record<string, number>
  frameworks: string[]
  databases: string[]
  infra: string[]
  complexity: string
  file_count: number
  team_source?: 'ai' | 'rules'
}

export interface DiscoverTeamAgent {
  name?: string
  role: string
  seniority: string
  specialty: string
  persona?: string
  reasoning?: string
  model?: string
  system_prompt?: string
  token_budget?: number
}

export interface DiscoverTeamResponse {
  discovery_id: number | null
  suggested_team: DiscoverTeamAgent[]
  detected_stack: DetectedStack
  /** Canonical host path of the scanned folder; send this to init_company. */
  project_path?: string
  /** Same shape as GET /v1/workspace/inspect; null when scanned on the server. */
  project?: WorkspaceInspection | null
}

export interface MemoryResult {
  content: string
  metadata: unknown
  similarity: number
}

// ── Help desk ───────────────────────────────────────────────────────────────

export interface SupportChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export type TicketSeverity = 'low' | 'medium' | 'high' | 'critical'
export type TicketCategory = 'bug' | 'feature' | 'question' | 'incident'
export type TicketStatus = 'open' | 'in_progress' | 'waiting' | 'resolved' | 'closed'

export interface BugReportRequest {
  title: string
  description: string
  steps?: string
  expected?: string
  actual?: string
  severity?: TicketSeverity
  reporter_email?: string
  browser_info?: Record<string, unknown>
}

export interface BugReportResponse {
  ticket_num: string
  status: string
  [key: string]: unknown
}

export interface TicketFilters {
  reporter_email?: string
  status?: TicketStatus
  severity?: TicketSeverity
  limit?: number
}

export interface SupportTicket {
  id: number
  ticket_num: string
  title: string
  /** What the reporter chose, or null when they chose none. */
  severity: string | null
  category: string | null
  status: string
  reporter_email: string | null
  assigned_to: string | null
  /** A support admin's decision, kept apart from the reporter's choice. */
  decided_severity?: string | null
  decided_category?: string | null
  created_at: string | null
  updated_at: string | null
  resolved_at: string | null
}

export interface TicketUpdateRequest {
  status: TicketStatus
  resolution?: string
  assigned_to?: string
  /**
   * The support admin's decision, stored apart from the reporter's choice and
   * the agent's suggestion. Omitted keeps the earlier decision; '' clears it.
   */
  severity?: TicketSeverity | ''
  category?: TicketCategory | ''
}

/** Per field: tickets the Support agent triaged and a person then decided. */
/** How the Reviewer agent's suggestions compared with the decisions people recorded on a company's runs. */
export interface ReviewerRecord {
  decided: number
  agent_agreed: number
  /** Decided runs the agent gave no usable answer for (misses too). */
  agent_unusable: number
  /** Decided runs the Verifier's verdict alone called (verified or refuted): its baseline. */
  verifier_called: number
  verifier_agreed: number
}

export interface AgentRecordField {
  decided: number
  agent_agreed: number
  /** Decided tickets the agent gave no usable answer for (misses too). */
  agent_unusable: number
  /** Decided tickets whose reporter chose a value: the reporters' baseline. */
  reporter_chose: number
  reporter_agreed: number
}

export interface SupportAgentRecord {
  severity: AgentRecordField
  category: AgentRecordField
}

export type CompanyRole = 'Owner' | 'Manager' | 'Viewer'

export type GitHubInclusionRule = 'all' | 'bots_only' | 'non_bots'

export interface GitHubBindingRequest {
  company_id: number
  owner: string
  repo: string
  webhook_secret: string
  inclusion_rule: GitHubInclusionRule
}

export interface GitHubBinding {
  id: number
  company_id: number
  owner: string
  repo: string
  inclusion_rule: GitHubInclusionRule
}

export interface GitHubBackfillResult {
  ingested: number
  skipped: number
  errors: { number: number | null; error: string }[]
}

export interface LineageEntry {
  engram_id: string
  role: string | null
  decision: string | null
  timestamp: string | null
  company_id: number | null
  legacy: boolean
}

export interface LineageResponse {
  file: string
  status: string
  lineage: LineageEntry[]
}

export interface SupportTicketDetail extends SupportTicket {
  description: string
  steps: string | null
  expected: string | null
  actual: string | null
  resolution: string | null
  /** The Support agent's triage: suggestions beside the reporter's choice. */
  agent_reply?: string | null
  suggested_severity?: string | null
  suggested_category?: string | null
  triaged_by?: string | null
  triaged_at?: string | null
  /** Who last changed the decision, and when. */
  decided_by?: string | null
  decided_at?: string | null
  [key: string]: unknown
}

// ── Workspace daemon (host-native project folders) ───────────────────────────
// Paths are host-native absolute strings (`/Users/ana/code`, `C:\Users\ana`).
// Treat them as opaque: never join or normalise them, always reuse the `path`
// the API returned.

/** `darwin`, `linux`, `win32`, or another Node platform string. */
export type WorkspacePlatform = 'darwin' | 'linux' | 'win32' | (string & {})

export interface WorkspaceHost {
  hostname: string
  platform: WorkspacePlatform
  home: string
  sep: string
}

export interface WorkspaceStatus {
  connected: boolean
  /** connected, absent (nothing listens) or unknown (the backend cannot tell); older backends omit it. */
  state?: 'connected' | 'absent' | 'unknown'
  /** Why the state is absent or unknown. */
  reason?: string | null
  host: WorkspaceHost | null
  jetstream?: boolean
}

export interface WorkspaceLocation {
  name: string
  path: string
}

export interface WorkspaceEntry extends WorkspaceLocation {
  is_git: boolean
}

export interface WorkspaceBrowseResponse {
  host: WorkspaceHost
  path: string
  parent: string | null
  entries: WorkspaceEntry[]
  shortcuts: WorkspaceLocation[]
  roots: WorkspaceLocation[]
  truncated: boolean
}

export type GitProvider = 'github' | 'gitlab' | 'bitbucket' | 'other'

export interface WorkspaceGitInfo {
  is_repo: boolean
  branch: string | null
  remote_url: string | null
  provider: GitProvider | null
  web_url: string | null
}

export interface WorkspaceInspection {
  host: WorkspaceHost
  path: string
  name: string
  exists: boolean
  is_dir: boolean
  git: WorkspaceGitInfo | null
}

export interface BacklogItem {
  id: number
  sprint_id: number
  title: string
  description?: string
  status: 'todo' | 'in_progress' | 'in_review' | 'done' | 'blocked'
  priority: 'low' | 'medium' | 'high' | 'critical'
  assignee?: string
  comments: { author: string; text: string; created_at: string }[]
  created_at: string
  updated_at: string
}

export interface SprintBoard {
  sprint: {
    id: number
    company_id: number
    sprint_name: string
    status: string
    goal?: string
    start_date: string
    scope_size: string
    item_limit: number
  }
  columns: Record<string, BacklogItem[]>
  total: number
}

export interface SprintSummary {
  id: number
  sprint_name: string
  status: string
  goal: string | null
  start_date: string | null
  scope_size: string
  total: number
  done: number
  /** Tasks blocked on the board, and rework requests over the sprint: the numbers procedures are judged by. */
  blocked: number
  rework: number
  /** Tasks carried over from an earlier sprint, how many got done, and the same for those the ScrumMaster briefed. */
  second_attempts: SecondAttempts
  /** Tasks a console assistant advised on and tasks none did: how many got done and how many rework requests each drew. */
  console_advice: ConsoleAdvice
  /** The same split for the Architect's briefs; a briefed task's rework counts from its first brief on. */
  architect_advice: ConsoleAdvice
}

export interface AdviceGroup {
  total: number
  done: number
  rework: number
}

export interface ConsoleAdvice {
  advised: AdviceGroup
  unadvised: AdviceGroup
}

export interface SecondAttempts {
  total: number
  done: number
  briefed: number
  briefed_done: number
}

export interface PlannedSprintTask {
  title: string
  description: string
  priority: 'low' | 'medium' | 'high' | 'critical'
  assignee: string
}

export interface SprintPlanResponse {
  sprint_name: string
  goal: string
  scope_size: 'S' | 'M' | 'L'
  tasks: PlannedSprintTask[]
}

// ── Orchestration Health types ────────────────────────────────────────────────

export interface OrchestrationHealthWeek {
  week: string
  qa_needs_work_rate: number
  avg_developer_tokens: number
  architect_consult_count: number
  task_count: number
  post_batch1: boolean
  /** Developer turns whose token usage was not reported: left out of the average, not counted as zero. */
  developer_turns_without_tokens?: number
}

export interface OrchestrationHealthSummary {
  qa_needs_work_rate: number
  avg_developer_tokens: number
}

export interface OrchestrationHealthResponse {
  anchor_commit: string
  anchor_date: string
  weeks: OrchestrationHealthWeek[]
  summary: {
    pre_batch1: OrchestrationHealthSummary
    post_batch1: OrchestrationHealthSummary
  }
}

export type AgentRunStatus = 'ingested' | 'verified' | 'refuted' | 'unverifiable'

export interface AgentRunApproval {
  id: number
  company_id: number
  agent_run_id: number
  approver_name: string
  decision: 'approved' | 'rejected'
  feedback: string | null
  rejection_category: 'scope' | 'quality' | 'security' | 'other' | null
  decided_at: string
  audit_log_id: number | null
}

/** What a message does in the conversation between roles. */
export const MESSAGE_KINDS = ['question', 'answer', 'handoff', 'request', 'decision', 'escalation', 'retrospective', 'proposal'] as const
export type MessageKind = typeof MESSAGE_KINDS[number]

/** One message between the company's agents. A claim, never evidence. */
export interface AgentMessage {
  id: number
  sprint_id: number | null
  backlog_item_id: number | null
  task_title: string | null
  from_name: string
  from_role: string
  /** null: the whole team. */
  to_role: string | null
  kind: MessageKind
  body: string
  created_at: string | null
}

export interface MessageFilters {
  sprint_id?: number
  backlog_item_id?: number
  kind?: MessageKind
  limit?: number
}

export type ProcedureStatus = 'proposed' | 'active' | 'rejected' | 'retired'
/** The role name of procedures every role follows. */
export const ALL_ROLES = 'All'

/** The board's numbers before a procedure (baseline) or after it (outcome). */
export interface ProcedureMetrics {
  sprints: number
  tasks: number
  rework_per_task: number
  blocked_rate: number
  /** On outcomes: kept, reverted, unmeasured, superseded, restored or retired. */
  result?: string
  by?: number | string
}

export interface Procedure {
  id: number
  role: string
  title: string
  body: string
  status: ProcedureStatus
  version: number
  supersedes_id: number | null
  proposed_by: string
  rationale: string | null
  source_sprint_id: number | null
  baseline: ProcedureMetrics | null
  outcome: ProcedureMetrics | null
  decided_by: string | null
  created_at: string | null
  decided_at: string | null
  retired_at: string | null
}

/** A task blocked until a person acts: the worker will not move it on its own. */
export interface InboxBlockedTask {
  id: number
  title: string
  assignee: string | null
  sprint_id: number
  sprint_name: string
  sprint_status: string
  reason: string
  /** The ScrumMaster's answer to the escalation, when it gave one: a claim for the person to weigh. */
  triage: { decision: 'retry' | 'person'; why: string; brief: string } | null
  frozen: boolean
  /** Approved by QA but high risk: waits for a person to accept it (mark it done) or send it back. */
  risk_hold?: boolean
  updated_at: string | null
}

export interface InboxProposal {
  id: number
  role: string
  title: string
  proposed_by: string
  source_sprint_id: number | null
  created_at: string | null
}

/** Everything the company needs a person for. */
export interface Inbox {
  blocked_tasks: InboxBlockedTask[]
  proposals: InboxProposal[]
  pending_runs: number
  total: number
}

export interface AgentRunListItem {
  id: number
  company_id: number
  external_ref: string
  version: number
  producer: string
  model: string | null
  agent_role: string | null
  subject: Record<string, unknown> | null
  claims: Record<string, unknown> | null
  artifact_digest: string
  artifact_size: number
  status: AgentRunStatus
  started_at: string | null
  finished_at: string | null
  ingested_at: string
  audit_log_id: number | null
  latest_approval: Pick<AgentRunApproval, 'decision' | 'feedback' | 'approver_name' | 'decided_at'> | null
  /** The Reviewer agent's suggestion: a claim beside the approval, never one. `reviewed_at` with no decision: its answer was unusable. */
  suggested_decision?: 'approved' | 'rejected' | null
  suggested_category?: 'scope' | 'quality' | 'security' | 'other' | null
  suggested_reason?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
}

export interface AgentRunFilters {
  producer?: string
  status?: AgentRunStatus
  limit?: number
  /** Exact match: every version of one piece of work, newest first. */
  external_ref?: string
  /** Runs whose `subject.sprint_id` is this sprint. */
  sprint_id?: number
  /** Leave out the company's own task worker and kickoff runs (the review loop decides them). */
  exclude_in_house?: boolean
}

export interface AgentRun extends Omit<AgentRunListItem, 'latest_approval'> {
  artifact_text: string | null
}

export interface VerificationCheck {
  name: string
  outcome: 'pass' | 'refuted' | 'unverifiable'
  observation: string
}

export interface AgentRunVerification {
  id: number
  verdict: Exclude<AgentRunStatus, 'ingested'>
  checks: VerificationCheck[] | null
  evidence: Record<string, unknown> | null
  observed_at: string
  audit_log_id: number | null
}

export interface AuditVerification {
  interaction_id: string
  rows: { id: number; action: string; status: 'valid' | 'invalid' | 'unsigned' | 'legacy'; mode: string; company_id?: number | null; legacy?: boolean }[]
  summary: { valid: number; invalid: number; unsigned: number; legacy: number }
}

export interface AgentRunApprovalRequest {
  company_id: number
  approver_name: string
  decision: 'approved' | 'rejected'
  feedback?: string
  rejection_category?: 'scope' | 'quality' | 'security' | 'other'
}

// ── Core fetch ───────────────────────────────────────────────────────────────

interface FetchOptions extends RequestInit {
  auth?: boolean
  params?: Record<string, string | number>
  /** Retry 5xx responses (default true). A 503 that means "not connected" should not. */
  retryServerErrors?: boolean
  _attempt?: number
}

let onUnauthorized: (() => void) | null = null

export function setOnUnauthorized(handler: (() => void) | null) {
  onUnauthorized = handler
}

async function fetchApi<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const { params, _attempt = 0, auth = true, retryServerErrors = true, ...fetchOptions } = options

  let url = `${API_BASE}${endpoint}`
  if (params) {
    const searchParams = new URLSearchParams(
      Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))
    )
    url += `?${searchParams.toString()}`
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const token = auth ? useAuthStore.getState().getValidToken() : null
    const headers = new Headers(fetchOptions.headers)
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    if (token) headers.set('Authorization', ['Bearer', token].join(' '))

    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers,
    })

    clearTimeout(timer)

    if (!response.ok) {
      if (
        response.status === 401 &&
        endpoint.split('?')[0] !== '/v1/auth/login' &&
        token &&
        useAuthStore.getState().token === token
      ) {
        useAuthStore.getState().logout()
        onUnauthorized?.()
      }
      if (response.status >= 500 && retryServerErrors && _attempt < MAX_RETRIES) {
        await delay(600 * (_attempt + 1))
        return fetchApi<T>(endpoint, { ...options, _attempt: _attempt + 1 })
      }
      throw new ApiError(response.status, friendlyMessage(response.status), await readDetail(response))
    }

    if (response.status === 204) return undefined as unknown as T
    return response.json() as Promise<T>

  } catch (err) {
    clearTimeout(timer)
    if (err instanceof ApiError) throw err
    if ((err as Error).name === 'AbortError') {
      if (_attempt < MAX_RETRIES) return fetchApi<T>(endpoint, { ...options, _attempt: _attempt + 1 })
      throw new ApiError(0, 'Request timed out. Please check your connection.')
    }
    if (_attempt < MAX_RETRIES) {
      await delay(600 * (_attempt + 1))
      return fetchApi<T>(endpoint, { ...options, _attempt: _attempt + 1 })
    }
    throw new ApiError(0, 'Network error. Please check your connection.')
  }
}

/** GET a file with the user's token; the caller saves it. */
async function fetchBlob(endpoint: string): Promise<{ blob: Blob; filename: string | null }> {
  const token = useAuthStore.getState().getValidToken()
  const headers = new Headers()
  if (token) headers.set('Authorization', ['Bearer', token].join(' '))
  const response = await fetch(`${API_BASE}${endpoint}`, { headers })
  if (!response.ok) {
    throw new ApiError(response.status, friendlyMessage(response.status), await readDetail(response))
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="?([^";]+)"?/.exec(disposition)
  return { blob: await response.blob(), filename: match ? match[1] : null }
}

async function readDetail(response: Response): Promise<string | undefined> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string' && detail) return detail
    // Some endpoints answer with {message, ...} (e.g. GitHub rate limits).
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
    return undefined
  } catch {
    return undefined
  }
}

function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}


export interface AgentActivity {
  total_tasks: number
  last_run_at: string | null
  total_cost_usd: number | null
  total_tokens: number
  avg_tokens: number
  last_model: string | null
}

export interface ManagedAgent {
  id: number
  company_id: number
  name: string
  role: string
  persona?: string | null
  seniority: string
  specialty: string
  model: string
  system_prompt?: string | null
  token_budget: number
  activity?: AgentActivity
}

export interface ModelCatalogEntry {
  id: string
  provider: string
  tier: string
  description: string
}

// ── Public API client ─────────────────────────────────────────────────────────

export const api = {
  get: <T>(endpoint: string, params?: Record<string, string | number>) =>
    fetchApi<T>(endpoint, { method: 'GET', params }),

  post: <T>(endpoint: string, data?: unknown) =>
    fetchApi<T>(endpoint, { method: 'POST', body: data ? JSON.stringify(data) : undefined }),

  put: <T>(endpoint: string, data: unknown) =>
    fetchApi<T>(endpoint, { method: 'PUT', body: JSON.stringify(data) }),

  patch: <T>(endpoint: string, data: unknown) =>
    fetchApi<T>(endpoint, { method: 'PATCH', body: JSON.stringify(data) }),

  delete: <T>(endpoint: string) =>
    fetchApi<T>(endpoint, { method: 'DELETE' }),

  // ── Agents ────────────────────────────────────────────────────────────────
  getAgents: (companyId: number) =>
    api.get<{ agents: ManagedAgent[] }>('/v1/agents', { company_id: companyId }),

  createAgent: (data: {
    company_id: number
    name: string
    role: string
    persona?: string
    seniority: string
    specialty: string
    model: string
    system_prompt?: string
    token_budget: number
  }) => api.post<ManagedAgent>('/v1/agents', data),

  generateAgentPrompt: (data: {
    role: string
    seniority: string
    specialty?: string
    persona?: string
  }) => api.post<{ system_prompt: string }>('/v1/agents/generate_prompt', data),

  updateAgent: (agentId: number, data: Partial<{
    name: string
    role: string
    persona: string
    seniority: string
    specialty: string
    model: string
    system_prompt: string
    token_budget: number
  }>) => api.patch<ManagedAgent>(`/v1/agents/${agentId}`, data),

  deleteAgent: (agentId: number) =>
    api.delete<{ status: string; agent: ManagedAgent }>(`/v1/agents/${agentId}`),

  pauseSprint: (sprintId: number) =>
    api.post<{ status: string }>(`/v1/sprints/${sprintId}/pause`, {}),

  resumeSprint: (sprintId: number) =>
    api.post<{ status: string }>(`/v1/sprints/${sprintId}/resume`, {}),

  /** Re-queues the sprint's todo items for the agents (Manager). 409 while paused. */
  dispatchSprint: (sprintId: number) =>
    api.post<{ dispatched: number; sprint_id?: number; message?: string }>(`/v1/sprints/${sprintId}/dispatch`, {}),

  login: (email: string, password: string) =>
    fetchApi<LoginResponse>('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  register: (data: { email: string; full_name: string; password: string }) =>
    fetchApi<RegisterResponse>('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  me: () => fetchApi<AuthProfile>('/v1/auth/me', { method: 'GET' }),

  // ── Domain Endpoints ───────────────────────────────────────────────────────

  // Core & Enterprise
  health: () => api.get<{ status: string; timestamp: string }>('/health'),
  // Probes each backing service; slow when one is down, so only on demand.
  deepHealth: () => fetchApi<DeepHealth>('/health/deep', { method: 'GET', auth: false, retryServerErrors: false }),
  capabilities: () => fetchApi<Capabilities>('/v1/capabilities', { method: 'GET', auth: false }),
  
  initCompany: (data: InitCompanyRequest) =>
    api.post<InitCompanyResponse>('/v1/init_company', data),

  discoverTeam: (companyId: number | null, projectPath: string) =>
    api.post<DiscoverTeamResponse>('/v1/discover_team', { company_id: companyId, project_path: projectPath }),

  // Workspace daemon. A 503 means "daemon not connected": do not retry it.
  workspaceStatus: () =>
    fetchApi<WorkspaceStatus>('/v1/workspace/status', { method: 'GET', retryServerErrors: false }),

  browseWorkspace: (path?: string) =>
    fetchApi<WorkspaceBrowseResponse>('/v1/workspace/browse', {
      method: 'GET',
      params: path ? { path } : undefined,
      retryServerErrors: false,
    }),

  inspectWorkspace: (path: string) =>
    fetchApi<WorkspaceInspection>('/v1/workspace/inspect', {
      method: 'GET',
      params: { path },
      retryServerErrors: false,
    }),

  getMessages: (companyId: number, filters: MessageFilters = {}) => {
    const params: Record<string, string | number> = { company_id: companyId }
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined) params[key] = value
    }
    return api.get<{ messages: AgentMessage[] }>('/v1/messages', params)
  },

  getInbox: (companyId: number) =>
    api.get<Inbox>('/v1/inbox', { company_id: companyId }),

  getProcedures: (companyId: number) =>
    api.get<{ procedures: Procedure[] }>('/v1/procedures', { company_id: companyId }),

  createProcedure: (data: { company_id: number; role: string; title: string; body: string }) =>
    api.post<Procedure>('/v1/procedures', data),

  decideProcedure: (procedureId: number, decision: 'adopt' | 'reject' | 'retire') =>
    api.post<Procedure>(`/v1/procedures/${procedureId}/${decision}`, {}),

  getAgentRuns: (companyId: number, filters: AgentRunFilters = {}) => {
    // Omit unset filters rather than sending them as the string "undefined".
    const params: Record<string, string | number> = { company_id: companyId }
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined) params[key] = typeof value === 'boolean' ? String(value) : value
    }
    return api.get<{ agent_runs: AgentRunListItem[] }>('/v1/agent_runs', params)
  },

  getAgentRun: (runId: number, companyId: number) =>
    api.get<AgentRun>(`/v1/agent_runs/${runId}`, { company_id: companyId }),

  getAgentRunVerifications: (runId: number, companyId: number) =>
    api.get<{ verifications: AgentRunVerification[] }>(`/v1/agent_runs/${runId}/verifications`, { company_id: companyId }),

  verifyAgentRun: (runId: number, companyId: number) =>
    api.post<AgentRunVerification>(`/v1/agent_runs/${runId}/verify`, { company_id: companyId }),

  getAgentRunApprovals: (runId: number, companyId: number) =>
    api.get<{ approvals: AgentRunApproval[] }>(`/v1/agent_runs/${runId}/approvals`, { company_id: companyId }),

  approveAgentRun: (runId: number, request: AgentRunApprovalRequest) =>
    api.post<AgentRunApproval>(`/v1/agent_runs/${runId}/approve`, request),

  getAuditVerification: (externalRef: string, companyId: number) =>
    api.get<AuditVerification>('/v1/audit/verify', {
      interaction_id: `agent-run:${externalRef}`,
      company_id: companyId,
    }),

  getQuotas: (companyId: number) =>
    api.get<any[]>('/v1/enterprise/quotas', { company_id: companyId }),
  getQuotaUsageHistory: (companyId: number, days = 7) =>
    api.get<{ days: { date: string; tokens: number }[]; total: number }>('/v1/enterprise/quota_usage_history', { company_id: companyId, days }),

  resetQuota: (buId: number) =>
    api.post<any>(`/v1/enterprise/quotas/${buId}/reset`, {}),

  getAnalyticsSummary: (sprintId: number) =>
    api.get<any>('/v1/analytics/summary', { sprint_id: sprintId }),

  getOrchestrationHealth: (companyId: number, weeks = 8) =>
    api.get<OrchestrationHealthResponse>('/v1/analytics/orchestration_health', { company_id: companyId, weeks }),

  // Sprints & Backlog
  listSprints: (companyId: number) =>
    api.get<SprintSummary[]>('/v1/sprints', { company_id: companyId }),

  getSprintBoard: (sprintId: number) =>
    api.get<SprintBoard>(`/v1/sprints/${sprintId}/board`),

  /** A short-lived ticket for the sprint's Glassroom stream; null when no login is required. */
  getStreamTicket: (sprintId: string) =>
    api.post<{ ticket: string | null; expires_in: number }>(
      `/v1/sprints/${encodeURIComponent(sprintId)}/stream_ticket`,
    ),

  updateBacklogItem: (itemId: number, data: {
    status?: string
    priority?: string
    assignee?: string
    comment?: string
  }) => api.patch<BacklogItem>(`/v1/backlog/${itemId}`, data),

  startSprint: (data: { company_id: number; sprint_name: string; start_date: string; scope_size: string; goal?: string; backlog_items: any[]; carry_over_ids?: number[] }) =>
    api.post<{ sprint_id: number; backlog_item_ids?: number[]; sprint_url?: string }>('/v1/start_sprint', data),

  planSprint: (data: { company_id: number; prompt: string; scope_size: 'S' | 'M' | 'L' }) =>
    api.post<SprintPlanResponse>('/v1/plan_sprint', data),

  planSelfImprovementSprint: (data: { company_id: number; scope_size: 'S' | 'M' | 'L' }) =>
    api.post<SprintPlanResponse>('/v1/plan_self_improvement_sprint', data),

  // Agents & Memory
  generate: (data: { company_id: number; story: string; constraints?: string; interaction_id?: string }) =>
    api.post<any>('/v1/generate', data),

  // Memory (pgvector + Neo4j). A 503 means the memory service is not connected.
  searchMemory: (query: string, options: { limit?: number; companyId?: number | null } = {}) =>
    fetchApi<{ results: MemoryResult[] }>('/v1/memory/search', {
      method: 'GET',
      params: {
        query,
        ...(options.limit ? { limit: options.limit } : {}),
        ...(options.companyId != null ? { company_id: options.companyId } : {}),
      },
      retryServerErrors: false,
    }),

  /** Stores *content* with its embedding (Manager). The API takes the text as a query parameter. */
  storeMemory: (content: string, options: { companyId?: number | null; metadata?: Record<string, unknown> } = {}) =>
    fetchApi<{ status: string }>('/v1/memory/store', {
      method: 'POST',
      params: {
        content,
        ...(options.companyId != null ? { company_id: options.companyId } : {}),
      },
      body: JSON.stringify(options.metadata ?? {}),
      retryServerErrors: false,
    }),

  // Support
  // Help desk (`/v1/support/*`).
  supportChat: (messages: SupportChatMessage[]) =>
    api.post<{ reply?: string }>('/v1/support/chat', { messages }),

  reportBug: (data: BugReportRequest) =>
    api.post<BugReportResponse>('/v1/support/report_bug', data),

  listTickets: (filters: TicketFilters = {}) => {
    const params: Record<string, string | number> = {}
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') params[key] = value
    }
    return api.get<{ tickets: SupportTicket[]; count: number }>('/v1/support/tickets', params)
  },

  getTicket: (ticketNum: string) =>
    api.get<SupportTicketDetail>(`/v1/support/tickets/${encodeURIComponent(ticketNum)}`),

  updateTicket: (ticketNum: string, data: TicketUpdateRequest) =>
    api.patch<{ ticket_num: string; status: TicketStatus; updated_at: string }>(
      `/v1/support/tickets/${encodeURIComponent(ticketNum)}`,
      data,
    ),

  /** How the Support agent's suggestions compared with support admins' decisions. */
  getSupportAgentRecord: () => api.get<SupportAgentRecord>('/v1/support/agent_record'),

  /** The Reviewer agent's record on a company's runs (Viewer). */
  getReviewerRecord: (companyId: number) =>
    api.get<ReviewerRecord>(`/v1/agent_runs/reviewer_record?company_id=${companyId}`),

  /** The audit log as a JSONL file; 404 until a workflow has written one. */
  downloadSupportLogs: () => fetchBlob('/v1/support/logs'),

  // Company members. Owners invite users who already have an account.
  // 404 when the email has no account, 409 when it is already a member.
  inviteMember: (data: { company_id: number; email: string; human_role: CompanyRole }) =>
    api.post<{ status: string; message: string }>('/v1/company/invite', data),

  // GitHub integration (Manager). There is no endpoint that lists bindings.
  createGitHubBinding: (data: GitHubBindingRequest) =>
    api.post<GitHubBinding>('/v1/integrations/github/bindings', data),

  backfillGitHub: (data: { company_id: number; owner: string; repo: string; since?: string }) =>
    fetchApi<GitHubBackfillResult>('/v1/integrations/github/backfill', {
      method: 'POST',
      body: JSON.stringify(data),
      retryServerErrors: false,
    }),

  // Decisions recorded for a file. Needs Neo4j; the API answers 500 without it.
  getLineage: (filePath: string, companyId?: number | null) =>
    fetchApi<LineageResponse>('/v1/enterprise/lineage', {
      method: 'GET',
      params: {
        file_path: filePath,
        ...(companyId != null ? { company_id: companyId } : {}),
      },
      retryServerErrors: false,
    }),
}
