import { afterEach, describe, expect, it } from 'vitest'
import { useAppStore } from './useAppStore'

describe('company sprint isolation', () => {
  afterEach(() => {
    useAppStore.getState().setCompany(null, null)
    useAppStore.getState().setActiveSprint(null)
  })

  it('resets the sprint only when the company id changes (issue #5)', () => {
    useAppStore.getState().setCompany(14, 'Company 14')
    useAppStore.getState().setActiveSprint(5)

    useAppStore.getState().setCompany(14, 'Renamed company')
    expect(useAppStore.getState()).toMatchObject({
      companyId: 14, companyName: 'Renamed company', activeSprintId: 5,
    })

    useAppStore.getState().setCompany(28, 'Company 28')
    expect(useAppStore.getState()).toMatchObject({
      companyId: 28, companyName: 'Company 28', activeSprintId: null,
    })
  })
})
