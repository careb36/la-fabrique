import { QueryClient } from '@tanstack/react-query'
import { isClientError } from '../services/api'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => !isClientError(error) && failureCount < 1,
    },
  },
})
