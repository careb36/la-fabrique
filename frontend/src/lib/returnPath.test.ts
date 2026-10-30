import { describe, expect, it } from 'vitest'
import { safeReturnPath } from './returnPath'

describe('safeReturnPath', () => {
  it.each(['/evidence/5', '/evidence/5?tab=checks#result'])(
    'accepts internal destination %s',
    destination => {
      expect(safeReturnPath(destination)).toBe(destination)
    },
  )

  it.each([
    '/\\example.com',
    '//example.com',
    'https://example.com',
    '/evidence%0A',
    '/evidence\u0000',
    '/login?from=%2F',
    '/companies/select',
    null,
  ])('falls back for unsafe destination %s', destination => {
    expect(safeReturnPath(destination)).toBe('/')
  })
})
