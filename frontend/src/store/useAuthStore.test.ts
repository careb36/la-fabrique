import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type AuthProfile } from '../services/api'
import { useAuthStore } from './useAuthStore'

const profile: AuthProfile = {
  user_id: 1,
  email: 'old@example.com',
  full_name: 'Old User',
  memberships: [{ company_id: 14, human_role: 'Owner' }],
}

describe('profile session isolation', () => {
  beforeEach(() => {
    useAuthStore.getState().logout()
    useAuthStore.setState({ token: 'old-token', expiresAt: Date.now() + 60_000 })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    useAuthStore.getState().logout()
  })

  it('discards a profile that resolves after logout (issue #2)', async () => {
    let resolveProfile!: (value: AuthProfile) => void
    vi.spyOn(api, 'me').mockReturnValue(new Promise(resolve => { resolveProfile = resolve }))
    const refresh = useAuthStore.getState().loadMe()

    useAuthStore.getState().logout()
    resolveProfile(profile)
    await refresh

    expect(useAuthStore.getState()).toMatchObject({
      token: null, user: null, memberships: [], meLoaded: false, loadingMe: false,
    })
  })

  it('discards an old profile and loading update after a session change (issue #2)', async () => {
    let resolveProfile!: (value: AuthProfile) => void
    vi.spyOn(api, 'me').mockReturnValue(new Promise(resolve => { resolveProfile = resolve }))
    const refresh = useAuthStore.getState().loadMe()
    useAuthStore.setState({ token: 'new-token', loadingMe: true })

    resolveProfile(profile)
    await refresh

    expect(useAuthStore.getState()).toMatchObject({
      token: 'new-token', user: null, memberships: [], meLoaded: false, loadingMe: true,
    })
  })

  it('discards old errors and loading updates after a session change (issue #2)', async () => {
    let rejectProfile!: (error: Error) => void
    vi.spyOn(api, 'me').mockReturnValue(new Promise((_, reject) => { rejectProfile = reject }))
    const refresh = useAuthStore.getState().loadMe()
    useAuthStore.setState({ token: 'new-token', loadingMe: true, profileError: null })

    rejectProfile(new Error('Old session failed'))
    await refresh.catch(() => {})

    expect(useAuthStore.getState()).toMatchObject({
      token: 'new-token', loadingMe: true, profileError: null,
    })
  })
})
