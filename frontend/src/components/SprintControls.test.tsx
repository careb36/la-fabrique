import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SprintControls, SprintStatusBanner, StartChoice } from './SprintControls'
import { queryClient } from '../lib/queryClient'
import { workControlApi, type SprintState } from '../services/workControl'
import { api } from '../services/api'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'

const sprint: SprintState = {
  id: 8, company_id: 1, sprint_name: 'S0', status: 'active', start_date: '', scope_size: 'M', item_limit: 8,
}

function wrap(node: React.ReactNode) {
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

function asRole(role: 'Manager' | 'Viewer') {
  useAuthStore.setState({ memberships: [{ company_id: 1, human_role: role }] } as never)
}

describe('sprint work controls', () => {
  beforeEach(() => {
    queryClient.clear()
    useAppStore.setState({ companyId: 1 })
    asRole('Manager')
    vi.spyOn(workControlApi, 'getAutonomy').mockResolvedValue({ company_id: 1, autonomy_level: 2 })
  })
  afterEach(() => {
    queryClient.clear()
    vi.restoreAllMocks()
  })

  it('offers Start for a planned sprint and starts it', async () => {
    const start = vi.spyOn(workControlApi, 'startSprint').mockResolvedValue({ status: 'active', dispatched: 3 })
    wrap(<SprintStatusBanner sprint={{ ...sprint, status: 'planned' }} />)
    expect(screen.getByText('This sprint has not started')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await waitFor(() => expect(start).toHaveBeenCalledWith(8))
  })

  it('says why the worker paused a sprint and resumes it', async () => {
    const resume = vi.spyOn(api, 'resumeSprint').mockResolvedValue({ status: 'active' })
    wrap(<SprintStatusBanner sprint={{ ...sprint, status: 'paused', pause_reason: 'No credit at deepseek: top up.' }} />)
    expect(screen.getByText('No credit at deepseek: top up.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    await waitFor(() => expect(resume).toHaveBeenCalledWith(8))
  })

  it('shows nothing while the sprint runs', () => {
    const { container } = wrap(<SprintStatusBanner sprint={sprint} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('stops a sprint only after the person confirms', async () => {
    const stop = vi.spyOn(workControlApi, 'stopSprint').mockResolvedValue({ status: 'cancelled', stopped_tasks: 2 })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    wrap(<SprintControls sprint={sprint} />)
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(stop).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(stop).toHaveBeenCalledWith(8))
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('offers neither Pause nor Stop on a finished sprint', () => {
    wrap(<SprintControls sprint={{ ...sprint, status: 'cancelled' }} />)
    expect(screen.queryByRole('button', { name: 'Pause' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dispatch pending' })).toBeDisabled()
  })

  it('lets a Manager change the autonomy level and a Viewer only read it', async () => {
    const set = vi.spyOn(workControlApi, 'setAutonomy').mockResolvedValue({ company_id: 1, autonomy_level: 1 })
    const { unmount } = wrap(<SprintControls sprint={sprint} />)
    const select = await screen.findByRole('combobox')
    expect(select).toHaveValue('2')
    fireEvent.change(select, { target: { value: '1' } })
    await waitFor(() => expect(set).toHaveBeenCalledWith(1, 1))
    unmount()
    queryClient.clear()
    asRole('Viewer')
    wrap(<SprintControls sprint={sprint} />)
    expect(await screen.findByRole('combobox')).toBeDisabled()
  })

  it('in the wizard, level 1 never starts on its own', () => {
    const onChange = vi.fn()
    const { rerender } = wrap(<StartChoice checked humanLed={false} onChange={onChange} />)
    expect(screen.getByRole('checkbox')).toBeChecked()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(false)
    rerender(<QueryClientProvider client={queryClient}><StartChoice checked humanLed onChange={onChange} /></QueryClientProvider>)
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByRole('checkbox')).toBeDisabled()
    expect(screen.getByText('At level 1 you always start it yourself.')).toBeInTheDocument()
  })
})
