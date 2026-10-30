import { describe, expect, it } from 'vitest'
import en from './en.json'
import es from './es.json'

function leafKeys(resource: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(resource).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'object' && value !== null
      ? leafKeys(value as Record<string, unknown>, path)
      : [path]
  }).sort()
}

describe('translation resources', () => {
  it('keeps English and Spanish leaf key sets identical', () => {
    expect(leafKeys(es)).toEqual(leafKeys(en))
  })
})
