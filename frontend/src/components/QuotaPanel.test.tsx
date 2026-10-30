import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QuotaPanel } from './QuotaPanel'
import { useQuotas, useResetQuota } from '../hooks/useQueries'
import { useAppStore } from '../store/useAppStore'

vi.mock('../hooks/useQueries', () => ({
  useQuotas: vi.fn(),
  useResetQuota: vi.fn(),
  useQuotaUsageHistory: vi.fn(() => ({ data: { days: [], total: 0 } })),
}))

describe('Company quotas', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ companyId: 42 })
    vi.mocked(useQuotas).mockReturnValue({
      data: [
        { id: 7, unit: 'Engineering', limit: 100, used: 85 },
        { id: 8, unit: 'Operations', limit: 100, used: 100 },
      ],
    } as never)
    vi.mocked(useResetQuota).mockReturnValue({ mutate: vi.fn() } as never)
  })

  it('retains usage, warning, exceeded and reset controls outside Review', () => {
    render(<QuotaPanel />)
    expect(useQuotas).toHaveBeenCalledWith(42)
    expect(screen.getByText('Engineering')).toBeInTheDocument()
    expect(screen.getByText('85%')).toBeInTheDocument()
    expect(screen.getByText('Near Limit')).toBeInTheDocument()
    expect(screen.getByText('Quota Exceeded')).toBeInTheDocument()
    fireEvent.click(screen.getAllByTitle('Reset quota counter')[0])
    expect(vi.mocked(useResetQuota)().mutate).toHaveBeenCalledWith(7, expect.objectContaining({ onSettled: expect.any(Function) }))
    expect(screen.getAllByTitle('Reset quota counter')[0]).toBeDisabled()
  })
})
