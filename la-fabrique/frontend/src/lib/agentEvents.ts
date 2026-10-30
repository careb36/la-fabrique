export type AgentFsmState = 'idle' | 'active' | 'waiting' | 'error'

export type GlassroomTaskPhase =
  | 'queued'
  | 'claimed'
  | 'context'
  | 'memory_retrieved'
  | 'execution'
  | 'deliverable'
  | 'artifact_generation'
  | 'qa_handoff'
  | 'qa_review'
  | 'qa_approved'
  | 'rework'
  | 'retry'
  | 'restart_recovery'
  | 'blocked_recovery'
  | 'quality_gate'
  | 'qa_gate'
  | 'implementation_complete'
  | 'kickoff_complete'
  | 'unknown'

export interface AssistantTelemetry {
  label?: string
  purpose?: string
  decision?: string
  detail?: string
}

export interface TaskTelemetry {
  id?: number
  title?: string
  status?: string
  phase?: GlassroomTaskPhase
  reworkCount?: number
  reworkLimit?: number
}

interface AgentEventBase {
  eventId: string
  timestamp: string
  rawType: string
  semanticType: string
  source: string
  task?: TaskTelemetry
  assistant?: AssistantTelemetry
}

export interface AgentNodeStartEvent extends AgentEventBase {
  kind: 'nodeStart'
  agentRole: string
  nodeName: string
  status: string
}

export interface AgentNodeEndEvent extends AgentEventBase {
  kind: 'nodeEnd'
  agentRole: string
  nodeName: string
}

export interface AgentNodeErrorEvent extends AgentEventBase {
  kind: 'nodeError'
  agentRole: string
  nodeName: string
  error: string
}

export interface AgentMessageEvent extends AgentEventBase {
  kind: 'agentMessage'
  agentRole: string
  content: string
}

export interface AgentSystemEvent extends AgentEventBase {
  kind: 'system'
  content: string
}

export interface AgentRetrospectiveEvent extends AgentEventBase {
  kind: 'retrospective'
  completionRate: number
  doneTasks: number
  totalTasks: number
  reworkCycles: number
  blockedTasks: number
  qaFailures: number
}

export type AgentEvent =
  | AgentNodeStartEvent
  | AgentNodeEndEvent
  | AgentNodeErrorEvent
  | AgentMessageEvent
  | AgentSystemEvent
  | AgentRetrospectiveEvent

function coerceTimestamp(value: unknown): string {
  return typeof value === 'string' && value.trim().length > 0
    ? value
    : new Date().toISOString()
}

function coerceRole(value: unknown, fallback = 'System'): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback
}

function coerceText(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback
}

function coerceNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function extractMessage(raw: Record<string, unknown>): string {
  return coerceText(raw.message, coerceText(raw.content, ''))
}

function extractTask(raw: Record<string, unknown>, fallbackTitle: string): TaskTelemetry | undefined {
  const id = coerceNumber(raw.task_id ?? raw.backlog_item_id)
  const title = coerceText(raw.task, fallbackTitle)
  const status = coerceText(raw.task_status, coerceText(raw.status))
  const phase = coerceText(raw.phase, 'unknown') as GlassroomTaskPhase
  const reworkCount = coerceNumber(raw.rework_count)
  const reworkLimit = coerceNumber(raw.rework_limit)

  if (id === undefined && !title && !status && phase === 'unknown' && reworkCount === undefined && reworkLimit === undefined) {
    return undefined
  }

  return {
    id,
    title: title || undefined,
    status: status || undefined,
    phase,
    reworkCount,
    reworkLimit,
  }
}

function extractAssistant(raw: Record<string, unknown>): AssistantTelemetry | undefined {
  const label = coerceText(raw.assistant_label)
  const purpose = coerceText(raw.assistant_purpose)
  const decision = coerceText(raw.assistant_decision)
  const detail = coerceText(raw.assistant_detail)

  if (!label && !purpose && !decision && !detail) {
    return undefined
  }

  return { label, purpose, decision, detail }
}

function semanticTypeFor(raw: Record<string, unknown>, explicitType: string): string {
  const semantic = coerceText(raw.semantic_type)
  if (semantic) return semantic

  switch (explicitType) {
    case 'connected':
      return 'stream.connected'
    case 'agent_start':
      return 'task.started'
    case 'agent_complete':
      return 'task.completed'
    case 'error':
      return 'task.error'
    case 'status':
      return 'task.status'
    case 'message':
      return 'agent.message'
    default:
      return 'stream.unknown'
  }
}

export function normalizeSSEEvent(raw: Record<string, unknown>): AgentEvent | null {
  const timestamp = coerceTimestamp(raw.timestamp)
  const explicitType = coerceText(raw.type)
  const semanticType = semanticTypeFor(raw, explicitType)
  const role = coerceRole(raw.role, coerceRole(raw.agent))
  const task = coerceText(raw.task, extractMessage(raw))
  const message = extractMessage(raw)
  const taskTelemetry = extractTask(raw, task)
  const assistant = extractAssistant(raw)
  const base = {
    eventId: coerceText(raw.event_id, crypto.randomUUID()),
    timestamp,
    rawType: explicitType || 'message',
    semanticType,
    source: coerceText(raw.source, 'backend'),
    task: taskTelemetry,
    assistant,
  }

  if (semanticType === 'stream.connected' || explicitType === 'connected') {
    const sprintId = coerceText(raw.sprint_id, 'current')
    return {
      ...base,
      kind: 'system',
      content: `Connected to GlassRoom stream for sprint ${sprintId}.`,
    }
  }

  if (explicitType === 'agent_start') {
    return {
      ...base,
      kind: 'nodeStart',
      agentRole: role,
      nodeName: task || 'task',
      status: message || `${role} started`,
    }
  }

  if (explicitType === 'agent_complete') {
    return {
      ...base,
      kind: 'nodeEnd',
      agentRole: role,
      nodeName: task || 'task',
    }
  }

  if (explicitType === 'error') {
    return {
      ...base,
      kind: 'nodeError',
      agentRole: role,
      nodeName: task || 'task',
      error: message || 'Unknown error',
    }
  }

  if (semanticType === 'sprint.retrospective' || explicitType === 'retrospective') {
    const retro = (raw.retro as Record<string, unknown>) || {}
    return {
      ...base,
      kind: 'retrospective',
      completionRate: typeof retro.completion_rate === 'number' ? retro.completion_rate : 0,
      doneTasks: typeof retro.done_tasks === 'number' ? retro.done_tasks : 0,
      totalTasks: typeof retro.total_tasks === 'number' ? retro.total_tasks : 0,
      reworkCycles: typeof retro.rework_cycles === 'number' ? retro.rework_cycles : 0,
      blockedTasks: typeof retro.blocked_tasks === 'number' ? retro.blocked_tasks : 0,
      qaFailures: typeof retro.qa_failures === 'number' ? retro.qa_failures : 0,
    }
  }

  if (explicitType === 'status') {
    const shouldSurfaceAsNodeStart = role !== 'System' || semanticType.startsWith('task.')

    if (semanticType === 'assistant.telemetry') {
      return {
        ...base,
        kind: 'system',
        content: message || task || 'Assistant telemetry update',
      }
    }

    if (semanticType === 'task.memory_retrieved' || semanticType === 'kickoff.memory_retrieved') {
      return {
        ...base,
        kind: 'system',
        content: message || 'Memory retrieved from past sprints.',
      }
    }

    if (shouldSurfaceAsNodeStart && role !== 'System') {
      return {
        ...base,
        kind: 'nodeStart',
        agentRole: role,
        nodeName: task || 'status',
        status: message || task || `${role} updated status`,
      }
    }
    return {
      ...base,
      kind: 'system',
      content: message || task || 'System status update',
    }
  }

  if (explicitType === 'message') {
    return {
      ...base,
      kind: 'agentMessage',
      agentRole: role,
      content: message || task,
    }
  }

  if (message && role !== 'System') {
    return {
      ...base,
      kind: 'agentMessage',
      agentRole: role,
      content: message,
    }
  }

  if (message) {
    return {
      ...base,
      kind: 'system',
      content: message,
    }
  }

  return null
}

const ROLE_COLOR_SEQUENCE = [
  'bg-sky-500/15 text-sky-200 border-sky-400/30',
  'bg-emerald-500/15 text-emerald-200 border-emerald-400/30',
  'bg-amber-500/15 text-amber-200 border-amber-400/30',
  'bg-rose-500/15 text-rose-200 border-rose-400/30',
  'bg-cyan-500/15 text-cyan-200 border-cyan-400/30',
  'bg-lime-500/15 text-lime-200 border-lime-400/30',
]

export function assignRolePalette(palettes: Record<string, string>, role: string): string {
  if (palettes[role]) return palettes[role]

  const normalizedRole = role.trim().toLowerCase()
  const seededPalettes: Record<string, string> = {
    po: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-400/30',
    productowner: 'bg-fuchsia-500/15 text-fuchsia-200 border-fuchsia-400/30',
    architect: 'bg-indigo-500/15 text-indigo-200 border-indigo-400/30',
    scrummaster: 'bg-violet-500/15 text-violet-200 border-violet-400/30',
    dev: 'bg-sky-500/15 text-sky-200 border-sky-400/30',
    developer: 'bg-sky-500/15 text-sky-200 border-sky-400/30',
    qa: 'bg-emerald-500/15 text-emerald-200 border-emerald-400/30',
    devops: 'bg-orange-500/15 text-orange-200 border-orange-400/30',
    system: 'bg-slate-500/15 text-slate-200 border-slate-400/30',
  }

  const seeded = seededPalettes[normalizedRole]
  if (seeded) return seeded

  const nextIndex = Object.keys(palettes).length % ROLE_COLOR_SEQUENCE.length
  return ROLE_COLOR_SEQUENCE[nextIndex]
}