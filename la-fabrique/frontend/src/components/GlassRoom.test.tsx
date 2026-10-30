import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import GlassRoom from './GlassRoom'

const feed = vi.hoisted(() => ({ messages: [] as unknown[], board: undefined as unknown }))

vi.mock('../hooks/useQueries', () => ({
  useSprintBoard: () => ({ data: feed.board }),
  useQuotas: () => ({ data: [] }),
}))

vi.mock('../store/agentStore', () => ({
  useAgentStore: () => ({
    messages: feed.messages,
    agentStates: {
      Developer: {
        role: 'Developer',
        fsmState: 'waiting',
        currentActivity: 'Browser agent activity',
        lastSeen: new Date().toISOString(),
      },
    },
    isConnected: true,
    connectionError: null,
    connect: vi.fn(),
    disconnect: vi.fn(),
    memoryHits: 0,
    lastRetro: null,
  }),
}))

afterEach(() => {
  vi.unstubAllGlobals()
  feed.messages = []
  feed.board = undefined
})

describe('GlassRoom scroll clearance', () => {
  it('reserves chat-button clearance in each desktop scroll pane without shrinking the roster', () => {
    vi.stubGlobal('requestAnimationFrame', vi.fn())
    const { container } = render(<GlassRoom sprintId="42" />)

    const scrollPanes = container.querySelectorAll('[class~="xl:pb-24"]')
    expect(scrollPanes).toHaveLength(3)
    for (const pane of scrollPanes) {
      expect(pane.className).toMatch(/(?:lg|xl):overflow-y-auto/)
    }

    const roster = screen.getByText('Browser agent activity').closest('.space-y-px')
    expect(roster).toHaveClass('shrink-0')
    expect(roster).not.toHaveClass('lg:min-h-0')
  })
})

describe('GlassRoom task links', () => {
  it('links task events that carry a task_id, and sprint tasks, to the task page', () => {
    vi.stubGlobal('requestAnimationFrame', vi.fn())
    const timestamp = new Date().toISOString()
    feed.messages = [
      { id: 'a', timestamp, agent: 'Developer', task: 'Encrypt credentials', taskId: 2, content: 'Working on it', type: 'agent_start' },
      { id: 'b', timestamp, agent: 'QA', task: 'Untracked chore', content: 'No backlog id', type: 'message' },
    ]
    feed.board = {
      sprint: { id: 42, sprint_name: 'Hardening', status: 'active', scope_size: 'M' },
      columns: { todo: [{ id: 5, sprint_id: 42, title: 'Write runbook', status: 'todo', priority: 'low', comments: [] }] },
      total: 1,
    }
    render(<MemoryRouter><GlassRoom sprintId="42" /></MemoryRouter>)

    const eventLink = screen.getByRole('link', { name: 'Encrypt credentials' })
    expect(eventLink).toHaveAttribute('href', '/sprints/42/tasks/2')
    expect(screen.queryByRole('link', { name: 'Untracked chore' })).not.toBeInTheDocument()
    expect(screen.getAllByText('Untracked chore').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Write runbook' })).toHaveAttribute('href', '/sprints/42/tasks/5')
  })
})
