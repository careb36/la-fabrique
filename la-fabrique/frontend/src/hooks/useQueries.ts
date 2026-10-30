import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'
import {
  api,
  ApiError,
  isClientError,
  type AgentRunApprovalRequest,
  type AgentRunFilters,
  type MessageFilters,
  type BacklogItem,
  type CompanyRole,
  type InitCompanyRequest,
  type ManagedAgent,
  type TicketFilters,
  type TicketUpdateRequest,
} from '../services/api'

// ── Keys ─────────────────────────────────────────────────────────────────────

export const QUERY_KEYS = {
  capabilities: () => ['capabilities'] as const,
  workspaceStatus: () => ['workspace', 'status'] as const,
  sprints: (companyId: number) => ['sprints', companyId] as const,
  sprintBoard: (id: number) => ['sprint', id, 'board'] as const,
  quotas: (companyId: number) => ['enterprise', companyId, 'quotas'] as const,
  quotaHistory: (companyId: number, days: number) => ['enterprise', companyId, 'quota_history', days] as const,
  analytics: (sprintId: number) => ['analytics', sprintId] as const,
  orchestrationHealth: (companyId: number, weeks: number) => ['orchestration_health', companyId, weeks] as const,
  tickets: (filters: TicketFilters) => ['tickets', filters] as const,
  ticket: (num: string) => ['ticket', num] as const,
  supportAgentRecord: () => ['support-agent-record'] as const,
  reviewerRecord: (companyId: number) => ['reviewer-record', companyId] as const,
  lineage: (companyId: number | null, file: string) => ['lineage', companyId, file] as const,
  memory: (companyId: number | null, query: string) => ['memory', companyId, query] as const,
  models: () => ['models'] as const,
  agents: (companyId: number) => ['agents', companyId] as const,
  agentRuns: (companyId: number, filters: AgentRunFilters = {}) =>
    ['agent-runs', companyId, filters.producer ?? '', filters.status ?? '', filters.limit ?? 50,
      filters.external_ref ?? '', filters.sprint_id ?? ''] as const,
  agentRun: (companyId: number, runId: number) => ['agent-run', companyId, runId] as const,
  procedures: (companyId: number) => ['procedures', companyId] as const,
  inbox: (companyId: number) => ['inbox', companyId] as const,
  messages: (companyId: number, filters: MessageFilters = {}) =>
    ['messages', companyId, filters.sprint_id ?? '', filters.backlog_item_id ?? '', filters.kind ?? '', filters.limit ?? ''] as const,
  verifications: (companyId: number, runId: number) => ['agent-run', companyId, runId, 'verifications'] as const,
  approvals: (companyId: number, runId: number) => ['agent-run', companyId, runId, 'approvals'] as const,
  auditVerification: (companyId: number | null, externalRef: string) =>
    ['audit-verification', companyId, externalRef] as const,
}

export function useCapabilities() {
  return useQuery({
    queryKey: QUERY_KEYS.capabilities(),
    queryFn: api.capabilities,
    staleTime: 1000 * 60 * 5,
  })
}

/**
 * Whether the native workspace daemon answers. Polls every 10 s while it is
 * not connected; stops once it is (or when the endpoint rejects the client).
 */
export function useWorkspaceStatus() {
  return useQuery({
    queryKey: QUERY_KEYS.workspaceStatus(),
    queryFn: api.workspaceStatus,
    refetchInterval: query =>
      query.state.data?.connected === true || isClientError(query.state.error) ? false : 10_000,
  })
}

// ── Enterprise & Company ─────────────────────────────────────────────────────

export function useAgentRuns(
  companyId: number | null,
  filters: AgentRunFilters = {},
) {
  return useQuery({
    queryKey: QUERY_KEYS.agentRuns(companyId ?? 0, filters),
    queryFn: () => api.getAgentRuns(companyId!, filters),
    enabled: companyId !== null,
  })
}

/**
 * What the company needs a person for: blocked tasks, proposals, undecided
 * runs. Polled, so the navigation badge follows the agents' work.
 */
export function useInbox(companyId: number | null, refreshMs: number | false = 30_000) {
  return useQuery({
    queryKey: QUERY_KEYS.inbox(companyId ?? 0),
    queryFn: () => api.getInbox(companyId!),
    enabled: companyId !== null,
    refetchInterval: refreshMs,
  })
}

export function useProcedures(companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.procedures(companyId ?? 0),
    queryFn: () => api.getProcedures(companyId!),
    enabled: companyId !== null,
  })
}

export function useCreateProcedure() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.createProcedure,
    onSuccess: (_result, { company_id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.procedures(company_id) })
    },
  })
}

export function useDecideProcedure(companyId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: 'adopt' | 'reject' | 'retire' }) =>
      api.decideProcedure(id, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.procedures(companyId ?? 0) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.inbox(companyId ?? 0) })
    },
  })
}

/** The conversation between roles; refreshed while the sprint is running. */
export function useAgentMessages(companyId: number | null, filters: MessageFilters = {}, refreshMs: number | false = false) {
  return useQuery({
    queryKey: QUERY_KEYS.messages(companyId ?? 0, filters),
    queryFn: () => api.getMessages(companyId!, filters),
    enabled: companyId !== null,
    refetchInterval: refreshMs,
  })
}

export function useAgentRun(companyId: number | null, runId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.agentRun(companyId ?? 0, runId ?? 0),
    queryFn: () => api.getAgentRun(runId!, companyId!),
    enabled: companyId !== null && runId !== null,
  })
}

export function useAgentRunVerifications(companyId: number | null, runId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.verifications(companyId ?? 0, runId ?? 0),
    queryFn: () => api.getAgentRunVerifications(runId!, companyId!),
    enabled: companyId !== null && runId !== null,
  })
}

export function useAgentRunApprovals(companyId: number | null, runId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.approvals(companyId ?? 0, runId ?? 0),
    queryFn: () => api.getAgentRunApprovals(runId!, companyId!),
    enabled: companyId !== null && runId !== null,
  })
}

export function useAuditVerification(externalRef: string | null, companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.auditVerification(companyId, externalRef ?? ''),
    queryFn: () => api.getAuditVerification(externalRef!, companyId!),
    enabled: externalRef !== null && companyId !== null,
  })
}

export function useVerifyAgentRun(companyId: number, runId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.verifyAgentRun(runId, companyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agentRun(companyId, runId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.verifications(companyId, runId) })
      queryClient.invalidateQueries({ queryKey: ['agent-runs', companyId] })
      queryClient.invalidateQueries({ queryKey: ['audit-verification'] })
    },
  })
}

export function useApproveAgentRun(companyId: number, runId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: AgentRunApprovalRequest) => api.approveAgentRun(runId, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.approvals(companyId, runId) })
      queryClient.invalidateQueries({ queryKey: ['agent-runs', companyId] })
      queryClient.invalidateQueries({ queryKey: ['audit-verification'] })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.reviewerRecord(companyId) })
    },
  })
}

export function useModels() {
  return useQuery({
    queryKey: QUERY_KEYS.models(),
    queryFn: () => api.get<{ models: any[], orchestrator?: string }>('/v1/models'),
    staleTime: 1000 * 60 * 60, // 1 hour
  })
}

export function useDiscoverTeam() {
  return useMutation({
    mutationFn: ({ companyId, projectPath }: { companyId: number | null, projectPath: string }) => 
      api.discoverTeam(companyId, projectPath),
  })
}

export function useInitCompany() {
  return useMutation({
    mutationFn: (data: InitCompanyRequest) => api.initCompany(data),
  })
}

// ── Sprints & Backlog ─────────────────────────────────────────────────────────

export function useStartSprint() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.startSprint,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sprint'] })
      queryClient.invalidateQueries({ queryKey: ['sprints'] })
    },
  })
}

export function usePlanSprint() {
  return useMutation({
    mutationFn: (data: Parameters<typeof api.planSprint>[0]) => api.planSprint(data),
  })
}

export function usePlanSelfImprovementSprint() {
  return useMutation({
    mutationFn: (data: Parameters<typeof api.planSelfImprovementSprint>[0]) => api.planSelfImprovementSprint(data),
  })
}

export function useSprints(companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.sprints(companyId ?? 0),
    queryFn: () => api.listSprints(companyId!),
    enabled: companyId !== null,
  })
}

export function useSprintBoard(sprintId: number | null) {
  const query = useQuery({
    queryKey: QUERY_KEYS.sprintBoard(sprintId || 0),
    queryFn: () => api.getSprintBoard(sprintId!),
    enabled: !!sprintId,
    staleTime: 1000 * 60 * 5, // 5 minutes
    refetchInterval: query => isClientError(query.state.error) ? false : 10_000,
  })

  useEffect(() => {
    if (query.error instanceof ApiError && [403, 404].includes(query.error.status)) {
      const state = useAppStore.getState()
      if (sprintId !== null && state.activeSprintId === sprintId) {
        state.setActiveSprint(null)
      }
    }
  }, [sprintId, query.error])

  return query
}

export function useUpdateBacklogItem() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ itemId, data }: { itemId: number, data: Parameters<typeof api.updateBacklogItem>[1] }) => 
      api.updateBacklogItem(itemId, data),
    onSuccess: (updatedItem: BacklogItem) => {
      if (updatedItem.sprint_id) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sprintBoard(updatedItem.sprint_id) })
      }
      queryClient.invalidateQueries({ queryKey: ['inbox'] })
    },
  })
}

// ── Enterprise & Analytics ───────────────────────────────────────────────────

export function useQuotas(companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.quotas(companyId || 0),
    queryFn: () => api.getQuotas(companyId!),
    enabled: !!companyId,
  })
}

export function useResetQuota() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (buId: number) => api.resetQuota(buId),
    onSuccess: (_data, _buId) => {
      // Invalidate all quota queries so the bar refreshes immediately.
      queryClient.invalidateQueries({ queryKey: ['enterprise'] })
    },
  })
}

export function useAnalyticsSummary(sprintId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.analytics(sprintId || 0),
    queryFn: () => api.getAnalyticsSummary(sprintId!),
    enabled: !!sprintId,
  })
}

export function useOrchestrationHealth(companyId: number | null, weeks = 8) {
  return useQuery({
    queryKey: QUERY_KEYS.orchestrationHealth(companyId || 0, weeks),
    queryFn: () => api.getOrchestrationHealth(companyId!, weeks),
    enabled: !!companyId,
  })
}

// ── Agents & Memory ──────────────────────────────────────────────────────────

export function useGenerate() {
  return useMutation({
    mutationFn: api.generate,
  })
}

export function useSearchMemory(query: string, companyId: number | null, limit = 10) {
  return useQuery({
    queryKey: [...QUERY_KEYS.memory(companyId, query), limit],
    queryFn: () => api.searchMemory(query, { companyId, limit }),
    enabled: query.trim().length > 0,
  })
}

export function useStoreMemory() {
  return useMutation({
    mutationFn: ({ content, companyId, metadata }: { content: string; companyId: number | null; metadata?: Record<string, unknown> }) =>
      api.storeMemory(content, { companyId, metadata }),
  })
}

// ── Support ──────────────────────────────────────────────────────────────────

export function useAgents(companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.agents(companyId || 0),
    queryFn: () => api.getAgents(companyId!),
    enabled: !!companyId,
    refetchInterval: 30_000,
  })
}

export function useCreateAgent(companyId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: Parameters<typeof api.createAgent>[0]) => api.createAgent(data),
    onSuccess: () => {
      if (companyId) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agents(companyId) })
      }
    },
  })
}

export function useUpdateAgentConfig(companyId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, data }: { agentId: number; data: Parameters<typeof api.updateAgent>[1] }) =>
      api.updateAgent(agentId, data),
    onSuccess: (updatedAgent: ManagedAgent) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agents(updatedAgent.company_id || companyId || 0) })
    },
  })
}

export function useDeleteAgent(companyId: number | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (agentId: number) => api.deleteAgent(agentId),
    onSuccess: () => {
      if (companyId) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agents(companyId) })
      }
    },
  })
}

export function useGenerateAgentPrompt() {
  return useMutation({
    mutationFn: (data: Parameters<typeof api.generateAgentPrompt>[0]) =>
      api.generateAgentPrompt(data),
  })
}


export function useQuotaUsageHistory(companyId: number | null, days = 7) {
  return useQuery({
    queryKey: QUERY_KEYS.quotaHistory(companyId || 0, days),
    queryFn: () => api.getQuotaUsageHistory(companyId!, days),
    enabled: !!companyId,
  })
}


export function useDispatchSprint() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sprintId: number) => api.dispatchSprint(sprintId),
    onSuccess: (_data, sprintId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sprintBoard(sprintId) })
    },
  })
}

export function usePauseSprint() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sprintId: number) => api.pauseSprint(sprintId),
    onSuccess: (_data, sprintId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sprintBoard(sprintId) })
    },
  })
}

export function useResumeSprint() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sprintId: number) => api.resumeSprint(sprintId),
    onSuccess: (_data, sprintId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sprintBoard(sprintId) })
    },
  })
}

// ── Help desk ───────────────────────────────────────────────────────────────

export function useTickets(filters: TicketFilters) {
  return useQuery({
    queryKey: QUERY_KEYS.tickets(filters),
    queryFn: () => api.listTickets(filters),
  })
}

export function useTicket(ticketNum: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.ticket(ticketNum ?? ''),
    queryFn: () => api.getTicket(ticketNum!),
    enabled: !!ticketNum,
  })
}

export function useUpdateTicket() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ticketNum, data }: { ticketNum: string; data: TicketUpdateRequest }) =>
      api.updateTicket(ticketNum, data),
    // Returned, so the caller's own onSuccess runs once the ticket is refetched.
    onSuccess: (_result, { ticketNum }) => Promise.all([
      queryClient.invalidateQueries({ queryKey: ['tickets'] }),
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.ticket(ticketNum) }),
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.supportAgentRecord() }),
    ]),
  })
}

/** How the Reviewer agent's suggestions compared with the decisions recorded on the company's runs. */
export function useReviewerRecord(companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.reviewerRecord(companyId ?? 0),
    queryFn: () => api.getReviewerRecord(companyId!),
    enabled: companyId !== null,
  })
}

/** Support admins only: how the Support agent's suggestions compared with their decisions. */
export function useSupportAgentRecord(enabled: boolean) {
  return useQuery({
    queryKey: QUERY_KEYS.supportAgentRecord(),
    queryFn: () => api.getSupportAgentRecord(),
    enabled,
  })
}

// ── Members, integrations, lineage ──────────────────────────────────────────

export function useInviteMember() {
  return useMutation({ mutationFn: api.inviteMember })
}

export function useCreateGitHubBinding() {
  return useMutation({ mutationFn: api.createGitHubBinding })
}

export function useBackfillGitHub() {
  return useMutation({ mutationFn: api.backfillGitHub })
}

export function useLineage(filePath: string, companyId: number | null) {
  return useQuery({
    queryKey: QUERY_KEYS.lineage(companyId, filePath),
    queryFn: () => api.getLineage(filePath, companyId),
    enabled: filePath.trim().length > 0,
  })
}

/** The signed-in user's role in the selected company, or null. */
export function useCurrentRole(): CompanyRole | null {
  const companyId = useAppStore(state => state.companyId)
  const memberships = useAuthStore(state => state.memberships)
  return memberships.find(m => m.company_id === companyId)?.human_role ?? null
}
