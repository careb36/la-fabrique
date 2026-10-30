import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SprintHealthChart } from './SprintHealthChart'

describe('SprintHealthChart', () => {
  it('renders with data', () => {
    render(
      <SprintHealthChart
        total={10}
        done={5}
        inProgress={3}
        blocked={2}
        healthScore={85}
      />
    )

    expect(screen.getByText('Sprint Health')).toBeInTheDocument()
    expect(screen.getByText('85')).toBeInTheDocument()
  })

  it('renders without data', () => {
    render(
      <SprintHealthChart
        total={0}
        done={0}
        inProgress={0}
        blocked={0}
        healthScore={null}
      />
    )

    expect(screen.getByText('No sprint data available')).toBeInTheDocument()
  })

  it('shows correct health color for high score', () => {
    render(
      <SprintHealthChart
        total={10}
        done={8}
        inProgress={2}
        blocked={0}
        healthScore={90}
      />
    )

    const score = screen.getByText('90')
    expect(score).toHaveClass('text-emerald-400')
  })

  it('shows correct health color for low score', () => {
    render(
      <SprintHealthChart
        total={10}
        done={2}
        inProgress={3}
        blocked={5}
        healthScore={45}
      />
    )

    const score = screen.getByText('45')
    expect(score).toHaveClass('text-red-400')
  })
})
