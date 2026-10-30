import { create } from 'zustand'
import { api } from '../services/api'
import {
  type AgentEvent,
  type AgentFsmState,
  type AssistantTelemetry,
  type TaskTelemetry,
  type AgentRetrospectiveEvent,
  normalizeSSEEvent,
  assignRolePalette,
} from '../lib/agentEvents'

export interface AgentMessage {
  id: string
  eventId?: string
  timestamp: string
  rawType?: string
  semanticType?: string
  source?: string
  agent: string
  role?: string
  task?: string
  taskId?: number
  taskStatus?: string
  taskPhase?: string
  reworkCount?: number
  reworkLimit?: number
  preview?: string
  assistantLabel?: string
  assistantPurpose?: string
  assistantDecision?: string
  assistantDetail?: string
  content: string
  type: 'message' | 'action' | 'status' | 'error' | 'agent_start' | 'agent_complete'
}

/** Per-agent live state derived from normalized AgentEvents (pixel-agents FSM pattern). */
export interface AgentLiveState {
  role: string
  fsmState: AgentFsmState
  currentActivity: string  // last formatted status from nodeStart
  color: string            // Tailwind color token (from assignRolePalette)
  lastSeen: string         // ISO timestamp
  lastTaskTitle?: string
  lastTaskId?: number
  lastSemanticType?: string
}

function assistantMetaFromTelemetry(assistant?: AssistantTelemetry) {
  return {
    assistantLabel: assistant?.label,
    assistantPurpose: assistant?.purpose,
    assistantDecision: assistant?.decision,
    assistantDetail: assistant?.detail,
  }
}

function taskMetaFromTelemetry(task?: TaskTelemetry) {
  return {
    taskId: task?.id,
    taskStatus: task?.status,
    taskPhase: task?.phase,
    reworkCount: task?.reworkCount,
    reworkLimit: task?.reworkLimit,
  }
}

export interface SprintRetro {
  completionRate: number
  doneTasks: number
  totalTasks: number
  reworkCycles: number
  blockedTasks: number
  qaFailures: number
  receivedAt: string
}

interface AgentStore {
  messages: AgentMessage[]
  agentStates: Record<string, AgentLiveState>   // keyed by agentRole
  rolePalettes: Record<string, string>           // role → Tailwind color token
  isConnected: boolean
  connectionError: string | null
  sprintId: string | null
  memoryHits: number          // times memory context was retrieved this session
  lastRetro: SprintRetro | null

  addMessage: (message: AgentMessage) => void
  applyAgentEvent: (event: AgentEvent) => void
  setConnected: (connected: boolean) => void
  setConnectionError: (error: string | null) => void
  setSprintId: (sprintId: string | null) => void
  clearMessages: () => void
  connect: (sprintId: string) => void
  disconnect: () => void
}

import {
  SSE_RECONNECT_DELAY_MS,
  SSE_MAX_RECONNECT_DELAY_MS,
  SSE_MAX_RECONNECT_ATTEMPTS,
  MAX_MESSAGES,
} from '../lib/constants'

import { API_BASE } from '../lib/apiBase'

const BACKEND_URL = API_BASE
const RECONNECT_DELAY_MS     = SSE_RECONNECT_DELAY_MS
const MAX_RECONNECT_ATTEMPTS = SSE_MAX_RECONNECT_ATTEMPTS
const MAX_RECONNECT_DELAY_MS = SSE_MAX_RECONNECT_DELAY_MS

let activeEventSource: EventSource | null = null
// The ids of the events shown since the last fresh connection (see addMessage).
const seenEventIds = new Set<string>()
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempt = 0
let connectionToken = 0

function clearReconnectTimer() {
  if (!reconnectTimer) return
  clearTimeout(reconnectTimer)
  reconnectTimer = null
}

function closeActiveEventSource() {
  if (!activeEventSource) return
  activeEventSource.close()
  activeEventSource = null
}

export const useAgentStore = create<AgentStore>((set, get) => {
  // An EventSource cannot send an Authorization header: with authentication
  // required the stream takes a short-lived ticket for the sprint, fetched
  // anew for every connection and reconnection. Without one (no login, or the
  // request failed) the stream is tried as is, and refuses when it must.
  const connectWithTicket = (sprintId: string, token: number) => {
    clearReconnectTimer()
    closeActiveEventSource()
    void api.getStreamTicket(sprintId)
      .then(({ ticket }) => ticket, () => null)
      .then((ticket) => {
        if (token !== connectionToken) return
        openConnection(sprintId, token, ticket)
      })
  }

  const openConnection = (sprintId: string, token: number, ticket: string | null) => {
    clearReconnectTimer()
    closeActiveEventSource()

    const params = new URLSearchParams({ sprint_id: sprintId })
    if (ticket) params.set('ticket', ticket)
    const eventSource = new EventSource(`${BACKEND_URL}/v1/glassroom/stream?${params}`)
    activeEventSource = eventSource

    eventSource.onopen = () => {
      if (token !== connectionToken || activeEventSource !== eventSource) {
        eventSource.close()
        return
      }
      reconnectAttempt = 0
      set({ isConnected: true, connectionError: null, sprintId })
    }

    eventSource.onmessage = (event) => {
      if (token !== connectionToken || activeEventSource !== eventSource) return

      try {
        const raw = JSON.parse(event.data) as Record<string, unknown>
        if (raw.ping) return

        const normalized = normalizeSSEEvent(raw)
        if (normalized) {
          const assistantMeta = assistantMetaFromTelemetry(normalized.assistant)
          const taskMeta = taskMetaFromTelemetry(normalized.task)
          const messageBase = {
            id: String(raw.id || normalized.eventId || crypto.randomUUID()),
            eventId: normalized.eventId,
            timestamp: normalized.timestamp,
            rawType: normalized.rawType,
            semanticType: normalized.semanticType,
            source: normalized.source,
            ...taskMeta,
            ...assistantMeta,
          }

          // Track memory hit counter.
          const semType = normalized.semanticType || ''
          if (semType === 'task.memory_retrieved' || semType === 'kickoff.memory_retrieved') {
            set((s) => ({ memoryHits: s.memoryHits + 1 }))
          }

          get().applyAgentEvent(normalized)

          if (normalized.kind === 'nodeStart') {
            get().addMessage({
              ...messageBase,
              agent: normalized.agentRole || 'System',
              role: normalized.agentRole || 'System',
              task: normalized.task?.title || normalized.nodeName,
              content: normalized.status,
              type: 'agent_start',
            })
          } else if (normalized.kind === 'nodeEnd') {
            get().addMessage({
              ...messageBase,
              agent: normalized.agentRole || 'System',
              role: normalized.agentRole || 'System',
              task: normalized.task?.title || normalized.nodeName,
              content: `${normalized.agentRole || 'System'} finished ${normalized.nodeName}`,
              type: 'agent_complete',
            })
          } else if (normalized.kind === 'agentMessage') {
            get().addMessage({
              ...messageBase,
              agent: normalized.agentRole || 'System',
              role: normalized.agentRole || 'System',
              task: normalized.task?.title || (typeof raw.task === 'string' ? raw.task : undefined),
              preview: typeof raw.preview === 'string' ? raw.preview : undefined,
              content: normalized.content,
              type: 'message',
            })
          } else if (normalized.kind === 'nodeError') {
            get().addMessage({
              ...messageBase,
              agent: normalized.agentRole || 'System',
              role: normalized.agentRole || 'System',
              task: normalized.task?.title || normalized.nodeName,
              content: `Error in ${normalized.nodeName}: ${normalized.error}`,
              type: 'error',
            })
          } else if (normalized.kind === 'system') {
            get().addMessage({
              ...messageBase,
              id: normalized.eventId || crypto.randomUUID(),
              agent: 'System',
              task: normalized.task?.title,
              content: normalized.content,
              type: 'status',
            })
          }
          return
        }

        get().addMessage({
          id: String(raw.id || crypto.randomUUID()),
          eventId: typeof raw.event_id === 'string' ? raw.event_id : undefined,
          timestamp: String(raw.timestamp || new Date().toISOString()),
          rawType: typeof raw.type === 'string' ? raw.type : undefined,
          semanticType: typeof raw.semantic_type === 'string' ? raw.semantic_type : undefined,
          source: typeof raw.source === 'string' ? raw.source : undefined,
          agent: String(raw.agent || 'System'),
          role: typeof raw.role === 'string' ? raw.role : undefined,
          task: typeof raw.task === 'string' ? raw.task : undefined,
          taskId: typeof raw.task_id === 'number' ? raw.task_id : undefined,
          taskStatus: typeof raw.task_status === 'string' ? raw.task_status : undefined,
          taskPhase: typeof raw.phase === 'string' ? raw.phase : undefined,
          reworkCount: typeof raw.rework_count === 'number' ? raw.rework_count : undefined,
          reworkLimit: typeof raw.rework_limit === 'number' ? raw.rework_limit : undefined,
          preview: typeof raw.preview === 'string' ? raw.preview : undefined,
          assistantLabel: typeof raw.assistant_label === 'string' ? raw.assistant_label : undefined,
          assistantPurpose: typeof raw.assistant_purpose === 'string' ? raw.assistant_purpose : undefined,
          assistantDecision: typeof raw.assistant_decision === 'string' ? raw.assistant_decision : undefined,
          assistantDetail: typeof raw.assistant_detail === 'string' ? raw.assistant_detail : undefined,
          content: String(raw.content || JSON.stringify(raw)),
          type:
            raw.type === 'agent_start' ||
            raw.type === 'agent_complete' ||
            raw.type === 'action' ||
            raw.type === 'status' ||
            raw.type === 'error' ||
            raw.type === 'message'
              ? raw.type
              : 'message',
        })
      } catch (error) {
        console.error('Failed to parse SSE message:', error)
      }
    }

    eventSource.onerror = () => {
      if (token !== connectionToken || activeEventSource !== eventSource) {
        eventSource.close()
        return
      }

      closeActiveEventSource()
      set({ isConnected: false })

      if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
        set({
          connectionError: `Could not reconnect after ${MAX_RECONNECT_ATTEMPTS} attempts.`,
        })
        return
      }

      const delay = Math.min(
        RECONNECT_DELAY_MS * 2 ** reconnectAttempt,
        MAX_RECONNECT_DELAY_MS,
      )
      reconnectAttempt += 1
      set({
        connectionError: `Connection lost. Reconnecting in ${Math.round(delay / 1000)}s...`,
      })

      reconnectTimer = setTimeout(() => {
        if (token !== connectionToken) return
        connectWithTicket(sprintId, token)
      }, delay)
    }
  }

  return {
    messages: [],
    agentStates: {},
    rolePalettes: {},
    isConnected: false,
    connectionError: null,
    sprintId: null,
    memoryHits: 0,
    lastRetro: null,

    addMessage: (message) => {
      // The backend replays the sprint's history on every connection, with
      // the same event ids each time: after a reconnection, what is already
      // shown is not shown again.
      if (message.eventId) {
        if (seenEventIds.has(message.eventId)) return
        seenEventIds.add(message.eventId)
      }
      set((state) => {
        const next = [...state.messages, message]
        return { messages: next.length > MAX_MESSAGES ? next.slice(-MAX_MESSAGES) : next }
      })
    },

    /**
     * Drive per-agent FSM state from a normalized AgentEvent.
     * Adapted from pixel-agents' hookEventHandler dispatch (markAgentWaiting,
     * handlePreToolUse, handleStop, etc.) — collapsed to a Zustand reducer.
     */
    applyAgentEvent: (event: AgentEvent) => {
      set((state) => {
        const palettes = { ...state.rolePalettes }
        const agentStates = { ...state.agentStates }

        const upsertRole = (role: string, patch: Partial<AgentLiveState>) => {
          const color = assignRolePalette(palettes, role)
          palettes[role] = color
          const defaults: AgentLiveState = {
            role,
            fsmState: 'idle',
            currentActivity: '',
            color,
            lastSeen: new Date().toISOString(),
            lastTaskTitle: undefined,
            lastTaskId: undefined,
            lastSemanticType: undefined,
          }
          agentStates[role] = Object.assign(
            defaults,
            agentStates[role] ?? {},
            patch,
            { lastSeen: event.timestamp || new Date().toISOString() },
          )
        }

        switch (event.kind) {
          case 'nodeStart':
            upsertRole(event.agentRole, {
              fsmState: 'active',
              currentActivity: event.status,
              lastTaskTitle: event.task?.title ?? event.nodeName,
              lastTaskId: event.task?.id,
              lastSemanticType: event.semanticType,
            })
            break
          case 'nodeEnd':
            upsertRole(event.agentRole, {
              fsmState: 'waiting',
              currentActivity: '',
              lastTaskTitle: event.task?.title ?? event.nodeName,
              lastTaskId: event.task?.id,
              lastSemanticType: event.semanticType,
            })
            break
          case 'nodeError':
            upsertRole(event.agentRole, {
              fsmState: 'error',
              currentActivity: event.error,
              lastTaskTitle: event.task?.title ?? event.nodeName,
              lastTaskId: event.task?.id,
              lastSemanticType: event.semanticType,
            })
            break
          case 'agentMessage':
            upsertRole(event.agentRole, {
              fsmState: 'active',
              currentActivity: event.content.slice(0, 60),
              lastTaskTitle: event.task?.title,
              lastTaskId: event.task?.id,
              lastSemanticType: event.semanticType,
            })
            break
          // 'system' events don't map to a specific role
          case 'retrospective': {
            const retro = event as AgentRetrospectiveEvent
            const retroEntry: SprintRetro = {
              completionRate: retro.completionRate,
              doneTasks: retro.doneTasks,
              totalTasks: retro.totalTasks,
              reworkCycles: retro.reworkCycles,
              blockedTasks: retro.blockedTasks,
              qaFailures: retro.qaFailures,
              receivedAt: retro.timestamp,
            }
            return { agentStates, rolePalettes: palettes, lastRetro: retroEntry }
          }
        }

        return { agentStates, rolePalettes: palettes }
      })
    },

    setConnected: (connected) => set({ isConnected: connected }),
    setConnectionError: (error) => set({ connectionError: error }),
    setSprintId: (sprintId) => set({ sprintId }),
    clearMessages: () => {
      seenEventIds.clear()
      set({ messages: [], agentStates: {}, rolePalettes: {}, memoryHits: 0, lastRetro: null })
    },

    connect: (sprintId) => {
      const token = ++connectionToken
      get().clearMessages()
      reconnectAttempt = 0
      clearReconnectTimer()
      closeActiveEventSource()
      set({ isConnected: false, sprintId, connectionError: null })
      connectWithTicket(sprintId, token)
    },

    disconnect: () => {
      connectionToken += 1
      reconnectAttempt = 0
      clearReconnectTimer()
      closeActiveEventSource()
      set({ isConnected: false, sprintId: null, connectionError: null })
    },
  }
})
