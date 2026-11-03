/**
 * Who decides when a sprint's agents work: start a planned sprint, stop one
 * for good, and the company's autonomy level. Pause, resume and dispatch stay
 * on `api` (`pauseSprint`, `resumeSprint`, `dispatchSprint`).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type SprintBoard } from './api'
import { QUERY_KEYS } from '../hooks/useQueries'

/** A sprint as the board returns it, with why the worker paused it. */
export type SprintState = SprintBoard['sprint'] & { pause_reason?: string | null }

export const workControlApi = {
  startSprint: (sprintId: number) =>
    api.post<{ status: string; dispatched: number }>(`/v1/sprints/${sprintId}/start`, {}),
  stopSprint: (sprintId: number) =>
    api.post<{ status: string; stopped_tasks: number }>(`/v1/sprints/${sprintId}/stop`, {}),
  getAutonomy: (companyId: number) =>
    api.get<{ company_id: number; autonomy_level: number }>(`/v1/companies/${companyId}/autonomy`),
  setAutonomy: (companyId: number, autonomyLevel: number) =>
    api.put<{ company_id: number; autonomy_level: number }>(`/v1/companies/${companyId}/autonomy`, {
      autonomy_level: autonomyLevel,
    }),
}

const autonomyKey = (companyId: number) => ['company', companyId, 'autonomy'] as const

function useSprintMutation(fn: (sprintId: number) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (_data, sprintId) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.sprintBoard(sprintId) })
    },
  })
}

export const useStartSprint = () => useSprintMutation(id => workControlApi.startSprint(id))
export const useStopSprint = () => useSprintMutation(id => workControlApi.stopSprint(id))

export function useAutonomy(companyId: number | null | undefined) {
  return useQuery({
    queryKey: autonomyKey(companyId ?? 0),
    queryFn: () => workControlApi.getAutonomy(companyId as number),
    enabled: Boolean(companyId),
  })
}

export function useSetAutonomy(companyId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (level: number) => workControlApi.setAutonomy(companyId, level),
    onSuccess: data => queryClient.setQueryData(autonomyKey(companyId), data),
  })
}
