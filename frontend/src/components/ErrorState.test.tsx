import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorState } from './ErrorState'

describe('ErrorState', () => {
  it('renders error message', () => {
    render(<ErrorState message="Something failed" />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Something failed')).toBeInTheDocument()
  })

  it('renders retry button when onRetry provided', () => {
    const onRetry = vi.fn()
    render(<ErrorState message="Error" onRetry={onRetry} />)

    const button = screen.getByText('Try again')
    expect(button).toBeInTheDocument()

    fireEvent.click(button)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('does not render retry button when onRetry not provided', () => {
    render(<ErrorState message="Error" />)
    expect(screen.queryByText('Try again')).not.toBeInTheDocument()
  })
})
