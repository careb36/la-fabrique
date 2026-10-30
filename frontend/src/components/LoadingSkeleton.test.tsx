import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LoadingSkeleton, CardSkeleton, TableSkeleton } from './LoadingSkeleton'

describe('LoadingSkeleton', () => {
  it('renders with message', () => {
    render(<LoadingSkeleton message="Loading..." />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('renders without message', () => {
    const { container } = render(<LoadingSkeleton />)
    expect(container.querySelector('svg.animate-spin')).toBeInTheDocument()
  })
})

describe('CardSkeleton', () => {
  it('renders placeholder', () => {
    render(<CardSkeleton />)
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
  })
})

describe('TableSkeleton', () => {
  it('renders default rows', () => {
    render(<TableSkeleton />)
    const rows = document.querySelectorAll('.animate-pulse')
    expect(rows.length).toBe(5)
  })

  it('renders custom rows', () => {
    render(<TableSkeleton rows={3} />)
    const rows = document.querySelectorAll('.animate-pulse')
    expect(rows.length).toBe(3)
  })
})
