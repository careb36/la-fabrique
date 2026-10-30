import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import AgentSettings from './AgentSettings'
import { useAppStore } from '../store/useAppStore'

type CatalogEntry = { id: string; provider: string; tier: string; description: string }

const catalogue = vi.hoisted(() => ({
  models: [] as CatalogEntry[],
  agents: [] as Record<string, unknown>[],
  role: null as string | null,
}))

vi.mock('../hooks/useQueries', () => {
  const mutation = () => ({ mutate: vi.fn(), isPending: false, isError: false })
  return {
    useAgents: () => ({ data: { agents: catalogue.agents }, isLoading: false, isError: false, refetch: vi.fn() }),
    useModels: () => ({ data: { models: catalogue.models, orchestrator: 'qwen3.6-flash' } }),
    useCreateAgent: mutation,
    useUpdateAgentConfig: mutation,
    useDeleteAgent: mutation,
    useGenerateAgentPrompt: mutation,
    useCurrentRole: () => catalogue.role,
  }
})

function modelSelect(): HTMLSelectElement {
  const select = screen.getByRole('option', { name: 'qwen3.7-plus (qwen)' }).closest('select')
  if (!select) throw new Error('model select not rendered')
  return select
}

function optionLabels(select: HTMLSelectElement): string[] {
  return within(select).getAllByRole('option').map(option => option.textContent ?? '')
}

describe('AgentSettings model selector', () => {
  beforeEach(() => {
    catalogue.models = [
      { id: 'deepseek-v4-pro', provider: 'deepseek', tier: 'balanced', description: 'DeepSeek deepseek-v4-pro' },
      { id: 'qwen3.6-flash', provider: 'qwen', tier: 'balanced', description: 'Qwen qwen3.6-flash' },
      { id: 'qwen3.7-plus', provider: 'qwen', tier: 'balanced', description: 'Qwen qwen3.7-plus' },
    ]
    catalogue.agents = []
    useAppStore.setState({ companyId: 1, companyName: 'Routing Corp' })
  })

  afterEach(() => {
    useAppStore.setState({ companyId: null, companyName: null })
  })

  it('lists the models from /v1/models after a "Default for role" option, selected by default', () => {
    render(<AgentSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'New agent' }))

    const select = modelSelect()
    expect(optionLabels(select)).toEqual([
      'Default for role',
      'deepseek-v4-pro (deepseek)',
      'qwen3.6-flash (qwen)',
      'qwen3.7-plus (qwen)',
    ])
    expect(select.value).toBe('')
    expect(screen.queryByText(/kimi-k2\.6/)).not.toBeInTheDocument()
  })

  it('lets a chosen model go back to "Default for role"', () => {
    render(<AgentSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'New agent' }))

    const select = modelSelect()
    fireEvent.change(select, { target: { value: 'deepseek-v4-pro' } })
    expect(select.value).toBe('deepseek-v4-pro')

    fireEvent.change(select, { target: { value: '' } })
    expect(select.value).toBe('')
  })
})

describe('AgentSettings for a Viewer', () => {
  beforeEach(() => {
    catalogue.models = [{ id: 'qwen3.6-flash', provider: 'qwen', tier: 'balanced', description: 'Qwen qwen3.6-flash' }]
    catalogue.agents = [{
      id: 7, company_id: 1, name: 'Dev Ana', role: 'Developer', persona: null, seniority: 'Senior', specialty: '',
      model: 'qwen3.6-flash', system_prompt: 'Write tests first.', token_budget: 500000, activity: null,
    }]
    useAppStore.setState({ companyId: 1, companyName: 'Routing Corp' })
  })

  afterEach(() => {
    catalogue.role = null
    useAppStore.setState({ companyId: null, companyName: null })
  })

  it('reads the agents but offers nothing to change them', () => {
    catalogue.role = 'Viewer'
    render(<AgentSettings />)

    expect(screen.getByRole('status')).toHaveTextContent('Only a Manager or the Owner changes them.')
    expect(screen.queryByRole('button', { name: 'New agent' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Duplicate/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Dev Ana/ }))
    expect(screen.getByDisplayValue('Write tests first.')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })

  it('offers the changes to a Manager', () => {
    catalogue.role = 'Manager'
    render(<AgentSettings />)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New agent' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Dev Ana/ }))
    expect(screen.getByDisplayValue('Write tests first.')).toBeEnabled()
  })
})
